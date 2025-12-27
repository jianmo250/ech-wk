import { connect } from 'cloudflare:sockets';

// ==========================================
// 配置区域
// ==========================================
// 优选 IP 列表 (用于竞速连接)
const CF_FALLBACK_IPS = [
  'tw.881288.xyz:443',
  '220.128.110.108:43',
  '60.251.232.240:995',
  '115.94.122.118:50001',
  'sg.881288.xyz:443',
  'sjc.o00o.ooo:443',
  '193.122.114.82:443'
];

// 鉴权 Token (留空则不验证)
const TOKEN = '1'; 

export default {
  async fetch(request, env, ctx) {
    try {
      const upgradeHeader = request.headers.get('Upgrade');
      
      // 1. 基础检查：是否为 WebSocket 请求
      if (!upgradeHeader || upgradeHeader.toLowerCase() !== 'websocket') {
        return new URL(request.url).pathname === '/' 
          ? new Response('', { status: 400 })
          : new Response('', { status: 426 });
      }

      // 2. 鉴权逻辑：检查 Sec-WebSocket-Protocol
      const protocolHeader = request.headers.get('Sec-WebSocket-Protocol');
      if (TOKEN && protocolHeader !== TOKEN) {
        return new Response('Unauthorized', { status: 401 });
      }

      // 3. 建立 WebSocket 对
      const webSocketPair = new WebSocketPair();
      const [client, server] = Object.values(webSocketPair);

      server.accept();
      
      // 4. 核心优化：使用 waitUntil 保持 Worker 活跃
      // 这能防止在异步 I/O 等待期间 Worker 被冻结
      ctx.waitUntil(handleSession(server));

      // 5. 构建响应头
      const responseInit = {
        status: 101,
        webSocket: client
      };
      
      // 如果客户端带了 Token，服务端响应时也要带回去，符合协议规范
      if (protocolHeader) {
        responseInit.headers = { 'Sec-WebSocket-Protocol': protocolHeader };
      }

      return new Response(null, responseInit);
      
    } catch (err) {
      return new Response(err.toString(), { status: 500 });
    }
  },
};

// ==========================================
// 会话处理逻辑
// ==========================================
async function handleSession(webSocket) {
  let remoteSocket = null;
  let writer = null;
  let reader = null;
  let isConnected = false;

  // 统一关闭函数：确保所有资源被释放，防止内存泄漏
  const close = () => {
    isConnected = false;
    try { webSocket.close(); } catch {}
    try { 
      if(remoteSocket) {
        remoteSocket.close();
      }
      // 释放流锁是必须的，否则下次无法复用或回收
      if(writer) writer.releaseLock();
      if(reader) reader.releaseLock();
    } catch {}
  };

  webSocket.addEventListener('message', async (event) => {
    try {
      const data = event.data;

      // 1. 极速模式：连接建立后的二进制数据直接透传
      if (data instanceof ArrayBuffer) {
        if (isConnected && writer) {
          // 优化：捕获写入错误，避免未捕获 Promise 导致 Worker 崩溃
          writer.write(new Uint8Array(data)).catch(close);
        }
        return;
      }

      // 2. 握手模式：处理 CONNECT 请求
      if (!isConnected && typeof data === 'string' && (data.includes('CONNECT') || data.includes('conn'))) {
        const parts = parseTarget(data);
        if (!parts) {
          webSocket.send('ERROR: Invalid target');
          return close();
        }

        // ============================================================
        // 核心优化：并发竞速连接 (Happy Eyeballs)
        // ============================================================
        remoteSocket = await raceConnect(parts.host, parts.port);
        
        if (!remoteSocket) {
          webSocket.send('ERROR: Connection failed');
          return close();
        }

        isConnected = true;
        
        // 获取读写流
        writer = remoteSocket.writable.getWriter();
        reader = remoteSocket.readable.getReader();

        // 告知客户端连接成功
        webSocket.send('CONNECTED');

        // 启动数据泵 (Remote -> WebSocket)
        // 这是一个异步循环，不使用 await，让它在后台运行
        pumpRemoteToWs(reader, webSocket).catch(close);
      }
    } catch (err) {
      close();
    }
  });

  webSocket.addEventListener('close', close);
  webSocket.addEventListener('error', close);
}

// ============================================================
// 核心函数：竞速连接 (Race)
// ============================================================
async function raceConnect(host, port) {
  const tasks = [];
  
  // 关键优化：TCP 参数调优
  const socketOptions = {
    secureTransport: 'off',
    allowHalfOpen: false,
    noDelay: true // 禁用 Nagle 算法，显著降低延迟
  };

  // 任务1: 直连 (Direct)
  // 解析：尝试直接由 Worker 连接目标，通常这是最快路径
  const directPromise = connect({ 
    hostname: host, 
    port: port 
  }, socketOptions);
  tasks.push(wrapPromise(directPromise));

  // 任务2: 优选 IP (Proxy/Fallback)
  // 解析：尝试连接指定的优选 IP，利用 SNI 路由机制
  const fallbackPromise = connectToFallback(host, port, socketOptions);
  tasks.push(wrapPromise(fallbackPromise));

  try {
    // Promise.any: 只要有一个成功，立即返回，无需等待另一个失败
    const winner = await Promise.any(tasks);
    return winner;
  } catch (err) {
    // 全部失败
    return null;
  }
}

// 辅助函数：连接优选 IP
async function connectToFallback(originalHost, originalPort, options) {
  // 随机选择一个优选 IP
  const fallbackStr = CF_FALLBACK_IPS[Math.floor(Math.random() * CF_FALLBACK_IPS.length)];
  const { host, port } = parseAddr(fallbackStr);
  
  try {
    // 如果优选 IP 字符串里没有端口，就用原目标的端口
    // 这里的原理是：连接到 CF 的节点 IP，但随后发送的 TLS ClientHello 包含原始 SNI
    const socket = connect({ 
      hostname: host, 
      port: port || originalPort 
    }, options);
    
    return socket;
  } catch (e) {
    throw e;
  }
}

// 辅助函数：确保 socket 真正连接建立 (Opened)
async function wrapPromise(promise) {
  try {
    const socket = await promise;
    await socket.opened; // 必须等待这一步，否则可能拿到未就绪的 socket
    return socket;
  } catch (e) {
    throw e;
  }
}

// ============================================================
// 高效数据泵 (Remote -> WebSocket)
// ============================================================
async function pumpRemoteToWs(reader, webSocket) {
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      
      // 检查 WebSocket 状态，避免在关闭状态下发送
      if (webSocket.readyState === WebSocket.OPEN) {
        webSocket.send(value);
      } else {
        break; // WS 已断开，停止读取
      }
    }
  } catch (e) {
    // 忽略读取错误
  } finally {
    // 确保释放锁，允许垃圾回收
    try { reader.releaseLock(); } catch {}
    // 如果 WS 还没关，顺手关掉
    if (webSocket.readyState === WebSocket.OPEN) webSocket.close();
  }
}

// ============================================================
// 解析工具函数
// ============================================================

// 解析目标地址，支持 conn:google.com:443 或 google.com:443
function parseTarget(data) {
  try {
    // 使用正则提取，比 split 更健壮
    // 移除 conn 或 connect 前缀
    const clean = data.replace(/^(CONNECT|conn)[\s:]+/i, '').trim();
    
    // 匹配 host 和 port
    const match = clean.match(/^([^:]+):(\d+)$/);
    if (match) {
      return { host: match[1], port: parseInt(match[2]) };
    }
    // 备用逻辑：如果只是 split
    const arr = clean.split(':');
    if (arr.length >= 2) {
       return { host: arr[0], port: parseInt(arr[1]) };
    }
    return null;
  } catch (e) { return null; }
}

// 解析优选 IP 地址
function parseAddr(str) {
  const lastColon = str.lastIndexOf(':');
  // IPv6 或 无端口的情况
  if (lastColon === -1) return { host: str, port: undefined };
  return {
    host: str.substring(0, lastColon),
    port: parseInt(str.substring(lastColon + 1))
  };
}
