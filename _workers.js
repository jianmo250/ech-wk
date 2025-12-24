import { connect } from 'cloudflare:sockets';

// ==========================================
// ==========================================
const CF_FALLBACK_IPS = [
  '115.94.122.118:50001',
  'sg.881288.xyz:443',
  'tw.881288.xyz:8443',
  '193.122.114.82:443',
  'sjc.o00o.ooo:443'
];

export default {
  async fetch(request, env, ctx) {
    const upgradeHeader = request.headers.get('Upgrade');
    if (!upgradeHeader || upgradeHeader !== 'websocket') {
      return new Response('Low Latency Proxy Active', { status: 200 });
    }

    const webSocketPair = new WebSocketPair();
    const [client, server] = Object.values(webSocketPair);

    server.accept();
    handleSession(server);

    return new Response(null, { status: 101, webSocket: client });
  },
};

async function handleSession(webSocket) {
  let remoteSocket = null;
  let writer = null;
  let reader = null;
  let isConnected = false;

  const close = () => {
    isConnected = false;
    try { webSocket.close(); } catch {}
    try { 
      if(remoteSocket) {
        remoteSocket.close();
        writer?.releaseLock();
        reader?.releaseLock();
      }
    } catch {}
  };

  webSocket.addEventListener('message', async (event) => {
    try {
      const data = event.data;

      // 1. 极速模式：二进制数据直接透传
      if (data instanceof ArrayBuffer) {
        if (isConnected && writer) {
          // 这里的 catch 是必须的，防止写入失败导致 Worker 崩溃
          writer.write(new Uint8Array(data)).catch(close);
        }
        return;
      }

      // 2. 握手模式：处理 CONNECT
      if (!isConnected && typeof data === 'string' && (data.includes('CONNECT') || data.includes('conn'))) {
        const parts = parseTarget(data);
        if (!parts) return close();

        // ============================================================
        // 核心优化：并发竞速连接 (Happy Eyeballs)
        // 同时发起直连和代理连接，谁快用谁，极大降低延迟
        // ============================================================
        remoteSocket = await raceConnect(parts.host, parts.port);
        
        if (!remoteSocket) {
          webSocket.send('ERROR: Connection failed');
          return close();
        }

        isConnected = true;
        writer = remoteSocket.writable.getWriter();
        reader = remoteSocket.readable.getReader();

        webSocket.send('CONNECTED');

        // 启动数据泵
        pumpRemoteToWs(reader, webSocket);
      }
    } catch (err) {
      close();
    }
  });

  webSocket.addEventListener('close', close);
  webSocket.addEventListener('error', close);
}

// ============================================================
// 新增核心函数：竞速连接
// ============================================================
async function raceConnect(host, port) {
  const tasks = [];

  // 任务1: 直连 (Direct)
  // 如果目标不是 CF，直连通常最快
  const directPromise = connect({ hostname: host, port: port });
  tasks.push(wrapPromise(directPromise, 'Direct'));

  // 任务2: 优选 IP (Proxy)
  // 专门解决 CF 网站无法直连或被墙网站连接慢的问题
  const fallbackPromise = connectToFallback(host, port);
  tasks.push(wrapPromise(fallbackPromise, 'Proxy'));

  try {
    // Promise.any 会等待第一个成功的，忽略失败的
    // 只要有一个连上了，马上返回，不用等另一个报错
    const winner = await Promise.any(tasks);
    
    // 这里的 winner 就是最快连上的那个 socket
    return winner;
  } catch (err) {
    // 两个都失败了
    return null;
  }
}

// 辅助函数：包装 Promise 以便我们知道谁赢了(可选，用于调试)
async function wrapPromise(promise, name) {
  try {
    const socket = await promise;
    await socket.opened; // 必须等待连接真正建立
    // console.log(`${name} connected!`);
    return socket;
  } catch (e) {
    throw e;
  }
}

async function connectToFallback(originalHost, originalPort) {
  // 随机取一个 IP
  const fallbackStr = CF_FALLBACK_IPS[Math.floor(Math.random() * CF_FALLBACK_IPS.length)];
  const { host, port } = parseAddr(fallbackStr);
  
  try {
    // 连接优选 IP
    const socket = connect({ 
      hostname: host, 
      port: port || originalPort 
    });
    return socket;
  } catch (e) {
    throw e;
  }
}

// 高效数据泵
async function pumpRemoteToWs(reader, webSocket) {
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (webSocket.readyState === 1) webSocket.send(value);
      else break;
    }
  } catch (e) {} 
  finally { if (webSocket.readyState === 1) webSocket.close(); }
}

function parseTarget(data) {
  try {
    const arr = data.split(':');
    return { host: arr[1], port: parseInt(arr[2]) || 443 };
  } catch (e) { return null; }
}

function parseAddr(str) {
  const lastColon = str.lastIndexOf(':');
  if (lastColon === -1) return { host: str, port: undefined };
  return {
    host: str.substring(0, lastColon),
    port: parseInt(str.substring(lastColon + 1))
  };
}
