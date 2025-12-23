import { connect } from 'cloudflare:sockets';

// ================= 配置区域 =================

// 指定优选 IP 的国家/地区策略
// 可选值: 'US', 'SG', 'JP', 'HK', 'TW', 'AUTO' (随机)
const TARGET_REGION = 'AUTO'; 

// 优选 IP 池 (解决 CF 无法访问 CF 的问题)
// 格式: 'IP:端口' 或 '域名:端口'
// 注意：为了速度，建议使用在该地区延迟最低的 881288 家族域名或直接 IP
const PROXY_IP_POOLS = {
  'SG': [ // 新加坡
    'sg.881288.xyz:443',
    '104.18.2.162:443',
    '104.19.2.162:443'
  ],
  'JP': [ // 日本
    'jp.881288.xyz:443',
    '104.16.12.162:443',
    '104.17.12.162:443'
  ],
  'TW': [ // 台湾
    'tw.881288.xyz:8443',
    '104.18.3.162:443'
  ],
  'HK': [ // 香港 (注意：HK 只有企业版 CF 才有较好连通性，通常会被绕路)
    '104.19.4.162:443'
  ],
  'US': [ // 美国 (主要用于 fallback)
    'sjc.o00o.ooo:443', 
    '193.122.114.82:443',
    '104.16.0.0:443'
  ],
  // 你的原始列表混杂池，用于 AUTO 模式补充
  'GENERAL': [
    '115.94.122.118:50001',
    '193.122.114.82:443',
    'www.visa.com:443',
    'www.csgo.com:443'
  ]
};

// ================= 代码逻辑 =================

const WS_READY_STATE_OPEN = 1;
const WS_READY_STATE_CLOSING = 2;

export default {
  async fetch(request, env, ctx) {
    const upgradeHeader = request.headers.get('Upgrade');
    if (!upgradeHeader || upgradeHeader !== 'websocket') {
      return new URL(request.url).pathname === '/' 
        ? new Response('CF-Worker-Proxy Active', { status: 200 })
        : new Response('Expected WebSocket', { status: 426 });
    }

    const webSocketPair = new WebSocketPair();
    const [client, server] = Object.values(webSocketPair);

    server.accept();
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
  
  const encoder = new TextEncoder();

  // 关闭连接清理
  const close = () => {
    isConnected = false;
    try { webSocket.close(); } catch {}
    try { 
      if(remoteSocket) {
        remoteSocket.close(); 
        // 释放 writer/reader 锁
        try{ writer?.releaseLock(); } catch {}
        try{ reader?.releaseLock(); } catch {}
      }
    } catch {}
  };

  webSocket.addEventListener('message', async (event) => {
    try {
      const data = event.data;

      // 1. 优先处理二进制数据 (传输阶段)
      if (data instanceof ArrayBuffer) {
        if (isConnected && writer) {
          // 这里的 await 会产生背压，保证不爆内存。
          // 如果追求极致速度且流量小，可以去掉 await，但有风险。
          await writer.write(new Uint8Array(data)); 
        }
        return;
      }

      // 2. 处理连接请求 (握手阶段)
      if (!isConnected && typeof data === 'string') {
        // 兼容 CONNECT:host:port 和 conn:host:port
        if (data.startsWith('CONNECT') || data.startsWith('conn')) {
          const parts = parseTarget(data);
          if (!parts) return close();

          // 尝试连接
          remoteSocket = await tryConnect(parts.host, parts.port, data);
          
          if (!remoteSocket) {
            webSocket.send('ERROR: Connection failed');
            return close();
          }

          isConnected = true;
          writer = remoteSocket.writable.getWriter();
          reader = remoteSocket.readable.getReader();

          webSocket.send('CONNECTED');

          // 启动管道：Remote -> WebSocket
          // 使用 pipeTo 极其高效，但因为我们要监控 WS 关闭，手动 pump 更加可控
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

// 数据泵：从 远程 Socket 读取并发送给 WebSocket
async function pumpRemoteToWs(reader, webSocket) {
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (webSocket.readyState === WS_READY_STATE_OPEN) {
        webSocket.send(value);
      } else {
        break;
      }
    }
  } catch (e) {
    // ignore
  } finally {
    if (webSocket.readyState === WS_READY_STATE_OPEN) webSocket.close();
  }
}

// 解析目标地址
function parseTarget(data) {
  // 格式示例: CONNECT:www.google.com:443|payload...
  // 我们只需要 host 和 port
  try {
    const arr = data.split(':');
    // arr[0] = CONNECT
    // arr[1] = host (可能包含 |)
    // arr[2] = port (可能包含 |)
    
    let host = arr[1];
    let portStr = arr[2];
    
    // 清理可能存在的 payload 分隔符 |
    if (host.includes('|')) host = host.split('|')[0];
    if (portStr.includes('|')) portStr = portStr.split('|')[0];
    
    return {
      host: host,
      port: parseInt(portStr) || 443
    };
  } catch (e) {
    return null;
  }
}

// 核心连接逻辑：直连 -> 优选 IP Fallback
async function tryConnect(host, port, originalData) {
  // 1. 尝试直连 (最快，如果目标不是 CF)
  try {
    const socket = connect({ hostname: host, port: port });
    await socket.opened;
    return socket;
  } catch (e) {
    // 直连失败，通常是因为目标是 Cloudflare (Error 1000/1101等)
    // 进入 Fallback 模式
  }

  // 2. 使用优选 IP 进行 Fallback 连接
  // 原理：连接到 CF 的任一 IP，利用 SNI 路由到真实目标
  const fallbackAddr = getFallbackAddress();
  
  try {
    // 注意：hostname 填优选 IP/域名，但 TLS SNI 还是由客户端在数据流中握手决定的
    // Worker 只是建立了一条 TCP 通道到 CF 边缘节点
    const socket = connect({ hostname: fallbackAddr.host, port: fallbackAddr.port || port });
    await socket.opened;
    return socket;
  } catch (e) {
    // Fallback 也失败了
    return null;
  }
}

// 获取优选 IP 逻辑
function getFallbackAddress() {
  let pool = [];
  
  // 根据配置选择池子
  if (TARGET_REGION !== 'AUTO' && PROXY_IP_POOLS[TARGET_REGION]) {
    pool = PROXY_IP_POOLS[TARGET_REGION];
  } else {
    // AUTO 模式：合并所有池子
    pool = [
      ...PROXY_IP_POOLS.SG,
      ...PROXY_IP_POOLS.JP,
      ...PROXY_IP_POOLS.US,
      ...PROXY_IP_POOLS.GENERAL
    ];
  }

  if (pool.length === 0) return { host: '104.16.0.0', port: 443 }; // 保底

  // 随机取一个，实现负载均衡
  const randomSelect = pool[Math.floor(Math.random() * pool.length)];
  
  // 解析 host:port
  const lastColon = randomSelect.lastIndexOf(':');
  if (lastColon === -1) return { host: randomSelect, port: 443 };
  
  return {
    host: randomSelect.substring(0, lastColon),
    port: parseInt(randomSelect.substring(lastColon + 1))
  };
}
