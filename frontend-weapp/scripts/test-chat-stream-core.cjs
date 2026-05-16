const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const ts = require("typescript");

const root = path.resolve(__dirname, "..");
const outfile = path.join(os.tmpdir(), `chat-stream-core-test-${process.pid}.cjs`);

function toArrayBuffer(bytes) {
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
}

function buildCoreModule() {
  const source = fs.readFileSync(path.join(root, "src/services/chat-stream-core.ts"), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020
    }
  });
  fs.writeFileSync(outfile, compiled.outputText);
  return require(outfile);
}

const {
  buildDisplayAnswerContent,
  buildChatStreamPayload,
  buildChatStreamUrl,
  createSSEParser,
  dedupeDisplayAnswer,
  decodeUtf8,
  normalizeApiBase,
  recordStreamChunkDiagnostics,
  recordStreamEventDiagnostics
} = buildCoreModule();

try {
  {
    assert.deepEqual(
      buildChatStreamPayload({
        user_id: "u1",
        session_id: "s1",
        question: "HTTP/3 是什么？",
        subject_id: "computer-network"
      }),
      {
        user_id: "u1",
        session_id: "s1",
        question: "HTTP/3 是什么？",
        subject_id: "computer-network",
        thinking_mode: false,
        allow_web: false
      }
    );
    assert.equal(
      buildChatStreamPayload({
        user_id: "u1",
        session_id: "s1",
        question: "联网搜索 HTTP/3 现状",
        subject_id: "computer-network",
        allow_web: true
      }).allow_web,
      true
    );
    const sharedPayload = buildChatStreamPayload({
      user_id: "u1",
      session_id: "s1",
      question: "今天有什么新标准？",
      subject_id: "computer-network",
      thinking_mode: false,
      allow_web: true
    });
    assert.deepEqual(sharedPayload, {
      user_id: "u1",
      session_id: "s1",
      question: "今天有什么新标准？",
      subject_id: "computer-network",
      thinking_mode: false,
      allow_web: true
    });
    const chatStreamSource = fs.readFileSync(path.join(root, "src/services/chat-stream.ts"), "utf8");
    assert.equal(
      (chatStreamSource.match(/data: requestPayload/g) || []).length,
      2,
      "chunked and sync fallback transports should both send requestPayload"
    );
    assert.equal(
      (chatStreamSource.match(/data: payload/g) || []).length,
      0,
      "chat transports should not bypass the normalized payload"
    );
    assert.ok(
      chatStreamSource.includes("CHAT_STREAM_API_BASE"),
      "chat stream transport should use the dedicated stream API base"
    );
    assert.ok(
      !chatStreamSource.includes("if (isContainerTransportEnabled())"),
      "container transport should not force chat streaming into sync fallback"
    );
  }

  {
    assert.equal(normalizeApiBase(" https://api.example.com/api/ "), "https://api.example.com/api");
    assert.equal(buildChatStreamUrl("https://api.example.com/api/"), "https://api.example.com/api/chat");
    assert.equal(buildChatStreamUrl(""), "");
  }

  {
    const messages = [];
    const parser = createSSEParser((message) => messages.push(message));
    parser.push('event: answer_delta\ndata: {"delta":"HT');
    parser.push('TP","streaming_mode":"token","is_synthetic_delta":false}\n\n');

    assert.equal(messages.length, 1);
    assert.equal(messages[0].event, "answer_delta");
    assert.deepEqual(JSON.parse(messages[0].data), {
      delta: "HTTP",
      streaming_mode: "token",
      is_synthetic_delta: false
    });
  }

  {
    const messages = [];
    const parser = createSSEParser((message) => messages.push(message));
    parser.push('event: answer_delta\r\ndata: {"delta":"A"}\r\n\r\nevent: done\ndata: {"message":"ok"}\n\n');

    assert.equal(messages.length, 2);
    assert.equal(messages[0].event, "answer_delta");
    assert.equal(messages[1].event, "done");
    assert.deepEqual(JSON.parse(messages[1].data), { message: "ok" });
  }

  {
    const messages = [];
    const parser = createSSEParser((message) => messages.push(message));
    const encoder = new TextEncoder();
    const decoder = new TextDecoder("utf-8");
    const raw = 'event: answer_delta\ndata: {"delta":"你好","streaming_mode":"token","is_synthetic_delta":false}\n\n';
    const encoded = encoder.encode(raw);
    const firstChineseByte = encoded.findIndex((byte) => byte === 0xe4);
    assert.ok(firstChineseByte > 0, "test fixture should contain a Chinese UTF-8 sequence");

    parser.push(decodeUtf8(toArrayBuffer(encoded.slice(0, firstChineseByte + 1)), decoder));
    parser.push(decodeUtf8(toArrayBuffer(encoded.slice(firstChineseByte + 1)), decoder));

    assert.equal(messages.length, 1);
    assert.deepEqual(JSON.parse(messages[0].data), {
      delta: "你好",
      streaming_mode: "token",
      is_synthetic_delta: false
    });
  }

  {
    assert.equal(
      buildDisplayAnswerContent(
        "HTTP 是 Web 中客户端和服务器之间通信的一套应用层规则。",
        {
          topic: "HTTP",
          steps: [
            "HTTP 的全称是 HyperText Transfer Protocol，中文叫超文本传输协议。",
            "它规定客户端如何请求资源、服务器如何返回资源。",
            "HTTP 采用请求-响应模型。"
          ]
        }
      ),
      "HTTP 是 Web 中客户端和服务器之间通信的一套应用层规则。\n\nHTTP 的全称是 HyperText Transfer Protocol，中文叫超文本传输协议。\n\n它规定客户端如何请求资源、服务器如何返回资源。\n\nHTTP 采用请求-响应模型。"
    );
    assert.equal(
      buildDisplayAnswerContent(
        "想象你在餐厅点餐：你是顾客，厨房是服务器，而服务员就是 HTTP。你想吃一份牛排，需要告诉服务员，服务员把要求送到厨房，再把做好的牛排端回来。",
        {
          topic: "HTTP",
          steps: [
            "HTTP 是 Web 中客户端和服务器之间通信的应用层协议。",
            "它采用请求-响应模型：浏览器发出请求，服务器返回响应。",
            "HTTP 本身无状态，常见易错点是不要把它当成传输层协议。"
          ]
        }
      ),
      "HTTP 是 Web 中客户端和服务器之间通信的应用层协议。\n\n它采用请求-响应模型：浏览器发出请求，服务器返回响应。\n\nHTTP 本身无状态，常见易错点是不要把它当成传输层协议。"
    );
    assert.equal(
      buildDisplayAnswerContent(
        "为什么需要HTTP：浏览器和服务器之间需要一种共同规则来交换网页资源。HTTP就是这种规则。HTTP是什么：HTTP 全称是超文本传输协议，是 Web 中客户端和服务器之间通信的应用层协议。HTTP如何工作：客户端发送请求，服务器返回响应。",
        { topic: "HTTP", steps: [] }
      ),
      "HTTP是什么：HTTP 全称是超文本传输协议，是 Web 中客户端和服务器之间通信的应用层协议。\n\n为什么需要HTTP：浏览器和服务器之间需要一种共同规则来交换网页资源。HTTP就是这种规则。\n\nHTTP如何工作：客户端发送请求，服务器返回响应。"
    );
    assert.equal(
      buildDisplayAnswerContent(
        "当你在浏览器输入网址时，浏览器会向服务器请求页面。HTTP 是 Web 中客户端和服务器之间通信的应用层协议。服务器再按照 HTTP 返回状态码、响应头和响应体。",
        { topic: "HTTP", steps: [] }
      ),
      "HTTP 是 Web 中客户端和服务器之间通信的应用层协议。\n\n当你在浏览器输入网址时，浏览器会向服务器请求页面。服务器再按照 HTTP 返回状态码、响应头和响应体。"
    );
    assert.equal(
      buildDisplayAnswerContent("", {
        topic: "HTTP",
        steps: ["HTTP 是应用层协议。", "它使用请求-响应模型。"]
      }),
      "HTTP 是应用层协议。\n\n它使用请求-响应模型。"
    );
    assert.equal(
      buildDisplayAnswerContent("用户想了解 HTTP 的基本概念。", {
        topic: "HTTP",
        steps: [
          "HTTP 是互联网通信的基础协议，需要从定义和作用几个方面来讲解。",
          "客户端发送请求，服务器返回响应。"
        ]
      }),
      "HTTP 是互联网通信的基础协议。\n\n客户端发送请求，服务器返回响应。"
    );
    assert.equal(dedupeDisplayAnswer("1 + 1 = 2。 1 + 1 = 2。"), "1 + 1 = 2。");
    assert.equal(
      dedupeDisplayAnswer("HTTP 是 Web 中客户端和服务器之间通信的一套应用层规则。 HTTP 是 Web 中客户端和服务器之间通信的一套应用层规则。"),
      "HTTP 是 Web 中客户端和服务器之间通信的一套应用层规则。"
    );
    assert.equal(
      dedupeDisplayAnswer("第一段。\n\n第一段。\n\n第二段。"),
      "第一段。\n\n第二段。"
    );
  }

  {
    const diagnostics = {
      transport: "chunked",
      chunkSupported: true,
      chunkCount: 0,
      parsedEventCount: 0,
      realTokenDeltaCount: 0,
      syntheticDeltaCount: 0
    };

    assert.deepEqual(recordStreamChunkDiagnostics(diagnostics, 12), { force: true });
    assert.equal(diagnostics.chunkCount, 1);
    assert.equal(diagnostics.firstChunkMs, 12);

    assert.deepEqual(recordStreamChunkDiagnostics(diagnostics, 20), { force: false });
    assert.equal(diagnostics.chunkCount, 2);
    assert.equal(diagnostics.firstChunkMs, 12);

    assert.deepEqual(
      recordStreamEventDiagnostics(
        diagnostics,
        "answer_delta",
        { delta: "HTTP", streaming_mode: "token", is_synthetic_delta: false },
        25
      ),
      { force: true }
    );
    assert.equal(diagnostics.parsedEventCount, 1);
    assert.equal(diagnostics.realTokenDeltaCount, 1);
    assert.equal(diagnostics.firstRealTokenDeltaMs, 25);

    assert.deepEqual(
      recordStreamEventDiagnostics(
        diagnostics,
        "answer_delta",
        { delta: " 是", streaming_mode: "token", is_synthetic_delta: false },
        30
      ),
      { force: false }
    );
    assert.equal(diagnostics.realTokenDeltaCount, 2);

    assert.deepEqual(
      recordStreamEventDiagnostics(
        diagnostics,
        "answer_delta",
        { delta: "HTTP 是应用层协议。", streaming_mode: "node", is_synthetic_delta: true },
        35
      ),
      { force: true }
    );
    assert.equal(diagnostics.syntheticDeltaCount, 1);
    assert.equal(diagnostics.degradedReason, "node_synthetic_delta");
  }

  console.log("chat-stream core tests passed");
} finally {
  fs.rmSync(outfile, { force: true });
}
