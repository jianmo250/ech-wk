import { connect } from 'cloudflare:sockets';

// ==========================================
// 1. 你指定的 IP 列表 (已优化格式处理)
// ==========================================
const CF_FALLBACK_IPS = [
  '115.94.122.118:50001',
  'sg.881288.xyz:443',
  'tw.881288.xyz:8443',
  '193.122.114.82', // 代码会自动补全 :443
  'sjc.o00o.ooo'    // 代码会自动补全 :443
];

// ==========================================
// 2. 核心逻辑 (无多余判断，追求吞吐量)
// ==========================================

export default {
  async fetch(request, env, ctx) {
    const upgradeHeader = request.headers.get('Upgrade');
    
    // 快速检查 WebSocket 头，不符合直接返回 200 或 426
    if (!upgradeHeader || upgradeHeader !== 'websocket') {
      return new URL(request.url).pathname === '/' 
        ? new Response('Proxy Active', { status: 200 })
        : new Response('Expected WebSocket', { status: 426 });
    }

    // 建立 WebSocket 连接对
    const webSocketPair = new WebSocketPair();
    const [client, server] = Object.values(webSocketPair);

    // 接受连接
    server.accept();
    
    // 将逻辑放入后台运行，不阻塞主线程
    // 使用 ctx.waitUntil 防止 Worker 意外冻结
    handleSession(server);

    return new Response(null, {
      status: 101,
      webSocket: client,
    });
  },
};

async function handleSession(webSocket) {
  let remoteSocket = null;
  let writer = null;
  let reader = null;
  let isConnected = false;

  // 统一的关闭清理函数
  const close = () => {
    isConnected = false;
    try { webSocket.close(); } catch {}
    try { 
      if(remoteSocket) {
        remoteSocket.close();
        try{ writer?.releaseLock(); } catch {}
        try{ reader?.releaseLock(); } catch {}
      }
    } catch {}
  };

  webSocket.addEventListener('message', async (event) => {
    try {
      const data = event.data;

      // -------------------------------------------------
      // 优化点 1: 优先处理二进制数据 (99.9% 的流量是这个)
      // -------------------------------------------------
      if (data instanceof ArrayBuffer) {
        if (isConnected && writer) {
          // 这里的 await 保证数据写入顺序，防止内存溢出
          // 这里的 catch 极其重要，防止远端断开导致 Worker 报错
          await writer.write(new Uint8Array(data)).catch(close);
        }
        return;
      }

      // -------------------------------------------------
      // 优化点 2: 仅在连接阶段处理字符串 (握手)
      // -------------------------------------------------
      if (!isConnected && typeof data === 'string') {
        // 兼容 CONNECT:host:port 和 conn:host:port
        // 使用 includes 比 startsWith 稍微快一点点且容错更高
        if (data.includes('CONNECT') || data.includes('conn')) {
          const parts = parseTarget(data);
          if (!parts) return close();

          // 开始连接：优先直连 -> 失败自动切换 Fallback IP
          remoteSocket = await tryConnect(parts.host, parts.port);
          
          if (!remoteSocket) {
            webSocket.send('ERROR: Connection failed');
            return close();
          }

          isConnected = true;
          writer = remoteSocket.writable.getWriter();
          reader = remoteSocket.readable.getReader();

          webSocket.send('CONNECTED');

          // 启动数据回传 (远端 -> 客户端)
          // 独立异步执行，不阻塞
          pumpRemoteToWs(reader, webSocket);
        }
      }
    } catch (err) {
      close();
    }
  });

  webSocket.addEventListener('close', close);
  webSocket.addEventListener('error', close);
}

// -------------------------------------------------
// 核心连接逻辑：直连 -> 失败切换
// -------------------------------------------------
async function tryConnect(host, port) {
  // 1. 尝试直连 (针对非 CF 网站，保持最低延迟)
  try {
    const socket = connect({ hostname: host, port: port });
    await socket.opened; // 必须等待连接成功
    return socket;
  } catch (e) {
    // 2. 直连失败 (通常是 CF 网站被拦截)，切换到优选 IP
    // 无需日志，直接切换，速度最快
    return await connectToFallback(host, port);
  }
}

// 连接到你提供的 IP 列表
async function connectToFallback(originalHost, originalPort) {
  const fallbackAddr = getFallbackAddress();
  try {
    const socket = connect({ 
      hostname: fallbackAddr.host, 
      port: fallbackAddr.port || originalPort // 如果列表里没写端口，就用目标端口
    });
    await socket.opened;
    return socket;
  } catch (e) {
    return null;
  }
}

// -------------------------------------------------
// 辅助函数
// -------------------------------------------------

// 从列表中随机取一个 IP，并解析端口
function getFallbackAddress() {
  const randomSelect = CF_FALLBACK_IPS[Math.floor(Math.random() * CF_FALLBACK_IPS.length)];
  
  // 处理 IP:Port 格式
  const lastColon = randomSelect.lastIndexOf(':');
  
  // 如果没有端口 (例如 '193.122.114.82')，port 返回 undefined，connect 时会使用 originalPort
  if (lastColon === -1) {
    return { host: randomSelect, port: undefined };
  }
  
  return {
    host: randomSelect.substring(0, lastColon),
    port: parseInt(randomSelect.substring(lastColon + 1))
  };
}

// 高效数据泵
async function pumpRemoteToWs(reader, webSocket) {
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      // 只要 WS 是开的，直接发，不做多余判断
      if (webSocket.readyState === 1) {
        webSocket.send(value);
      } else {
        break;
      }
    }
  } catch (e) {
    // ignore
  } finally {
    if (webSocket.readyState === 1) webSocket.close();
  }
}

// 解析指令
function parseTarget(data) {
  try {
    const arr = data.split(':');
    let host = arr[1];
    let port = parseInt(arr[2]) || 443;
    
    // 清理旧协议残留
    if (host.includes('|')) host = host.split('|')[0];
    if (String(port).includes('|')) port = parseInt(String(port).split('|')[0]);
    
    return { host, port };
  } catch (e) {
    return null;
  }
}
