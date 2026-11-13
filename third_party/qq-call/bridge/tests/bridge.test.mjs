import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import net from "node:net";
import http from "node:http";
import test from "node:test";

import {
  buildAcceptParams,
  callerAllowed,
  parseBridgeSettings,
  plugin_cleanup,
  plugin_init,
  summarizeValue,
} from "../napcat-plugin/index.mjs";

test("verified native Accept mapping uses the inviter as the session key", () => {
  const invite = [
    1,
    "inviter-uid",
    ["bot-uid"],
    3,
    "relation-id",
    5,
    6,
    7,
    8,
    9,
    1,
    "denoise-model",
  ];
  assert.deepEqual(buildAcceptParams(invite), [
    1,
    "inviter-uid",
    ["inviter-uid"],
    3,
    "relation-id",
    true,
    "denoise-model",
  ]);
});

test("invalid invite shape is rejected before invoking AVSDK", () => {
  assert.throws(() => buildAcceptParams([1, "uid"]), /incomplete/);
  const invite = Array(12).fill(null);
  assert.throws(() => buildAcceptParams(invite), /native Accept signature/);
});

test("diagnostic summaries redact sensitive fields and omit string contents", () => {
  const summary = summarizeValue({
    accessToken: "do-not-log-this",
    callerName: "Alice",
    nested: { cookie: "also-secret" },
  });
  const serialized = JSON.stringify(summary);
  assert.doesNotMatch(serialized, /do-not-log-this|also-secret|Alice/);
  assert.equal(summary.keys.find((item) => item.key === "accessToken").value, "[REDACTED]");
});

test("bridge settings load generated config and allow environment port overrides", () => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "maibot-qq-call-"));
  try {
    fs.writeFileSync(
      path.join(tempDir, "bridge-config.json"),
      JSON.stringify({
        controlHost: "127.0.0.1",
        controlPort: 6110,
        avHost: "localhost",
        avPort: 6111,
        tokenFile: "/run/private/token",
      }),
    );
    const settings = parseBridgeSettings(
      { MAIBOT_QQ_CALL_BRIDGE_PORT: "6210" },
      tempDir,
    );
    assert.equal(settings.controlPort, 6210);
    assert.equal(settings.avHost, "localhost");
    assert.equal(settings.tokenFile, "/run/private/token");
    assert.equal(settings.token, "");
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
});

test("bridge refuses non-loopback endpoints", () => {
  assert.throws(
    () => parseBridgeSettings({ MAIBOT_QQ_CALL_BRIDGE_HOST: "0.0.0.0" }, os.tmpdir()),
    /loopback/,
  );
});

async function unusedLoopbackPort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  const selectedPort = address.port;
  await new Promise((resolve) => server.close(resolve));
  return selectedPort;
}

test("NapCat lifecycle exposes only authenticated call state", async () => {
  const controlPort = await unusedLoopbackPort();
  const avPort = await unusedLoopbackPort();
  const previous = {
    token: process.env.MAIBOT_QQ_CALL_BRIDGE_TOKEN,
    tokenFile: process.env.MAIBOT_QQ_CALL_BRIDGE_TOKEN_FILE,
    controlPort: process.env.MAIBOT_QQ_CALL_BRIDGE_PORT,
    avPort: process.env.MAIBOT_QQ_CALL_AV_HOST_PORT,
  };
  const token = "test-token-that-is-longer-than-thirty-two-bytes";
  process.env.MAIBOT_QQ_CALL_BRIDGE_TOKEN = token;
  delete process.env.MAIBOT_QQ_CALL_BRIDGE_TOKEN_FILE;
  process.env.MAIBOT_QQ_CALL_BRIDGE_PORT = String(controlPort);
  process.env.MAIBOT_QQ_CALL_AV_HOST_PORT = String(avPort);

  let registeredListener = null;
  const service = {
    isNull: () => false,
    addKernelAVSDKListener(value) {
      registeredListener = value;
      return 7;
    },
    removeKernelAVSDKListener(id) {
      assert.equal(id, 7);
      registeredListener = null;
    },
  };
  const context = {
    logger: { info() {}, warn() {}, error() {} },
    router: { get() {} },
    core: {
      selfInfo: {},
      context: { session: { getAVSDKService: () => service } },
    },
  };

  try {
    await plugin_init(context);
    assert.ok(registeredListener);
    const baseUrl = `http://127.0.0.1:${controlPort}`;
    const health = await fetch(`${baseUrl}/healthz`);
    assert.equal(health.status, 200);
    const unauthorized = await fetch(`${baseUrl}/v1/calls/current`);
    assert.equal(unauthorized.status, 401);
    const authorized = await fetch(`${baseUrl}/v1/calls/current`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    assert.equal(authorized.status, 200);
    const payload = await authorized.json();
    assert.equal(payload.data.phase, "idle");
  } finally {
    await plugin_cleanup();
    for (const [key, value] of Object.entries(previous)) {
      const envName = {
        token: "MAIBOT_QQ_CALL_BRIDGE_TOKEN",
        tokenFile: "MAIBOT_QQ_CALL_BRIDGE_TOKEN_FILE",
        controlPort: "MAIBOT_QQ_CALL_BRIDGE_PORT",
        avPort: "MAIBOT_QQ_CALL_AV_HOST_PORT",
      }[key];
      if (value === undefined) delete process.env[envName];
      else process.env[envName] = value;
    }
  }
  assert.equal(registeredListener, null);
});


test("only an explicitly approved resolved caller may be answered", () => {
  assert.equal(callerAllowed("123456789", "123456789"), true);
  assert.equal(callerAllowed("123456789", "987654321"), false);
  assert.equal(callerAllowed("123456789", null), false);
  assert.equal(callerAllowed("", "123456789"), false);
  assert.equal(callerAllowed("*", "123456789"), false);
});


test("auto-accept fails closed and only accepts the verified caller with a live worker", async () => {
  const controlPort = await unusedLoopbackPort(), avPort = await unusedLoopbackPort();
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "saber-call-test-"));
  const readyFile = path.join(directory, "ready");
  const armFile = path.join(directory, "armed");
  const names = ["MAIBOT_QQ_CALL_BRIDGE_TOKEN", "MAIBOT_QQ_CALL_BRIDGE_PORT", "MAIBOT_QQ_CALL_AV_HOST_PORT", "SABER_QQ_CALL_ALLOWED_UIN", "SABER_QQ_CALL_READY_FILE", "SABER_QQ_CALL_ARM_FILE"];
  const old = Object.fromEntries(names.map(k => [k, process.env[k]]));
  Object.assign(process.env, { MAIBOT_QQ_CALL_BRIDGE_TOKEN: "test-token-longer-than-thirty-two-bytes", MAIBOT_QQ_CALL_BRIDGE_PORT: String(controlPort), MAIBOT_QQ_CALL_AV_HOST_PORT: String(avPort), SABER_QQ_CALL_ALLOWED_UIN: "123456789", SABER_QQ_CALL_READY_FILE: readyFile, SABER_QQ_CALL_ARM_FILE: armFile });
  let listener, actualUin = "999999999", accepts = 0;
  const fakeHost = http.createServer((req,res) => { let raw=""; req.on("data",v=>raw+=v); req.on("end",()=>{if(JSON.parse(raw).command===5) accepts++; res.end("{}");}); });
  await new Promise(resolve=>fakeHost.listen(avPort,"127.0.0.1",resolve));
  const service={isNull:()=>false,addKernelAVSDKListener(v){listener=v;return 1;},removeKernelAVSDKListener(){}};
  const session={getAVSDKService:()=>service,getUixConvertService:()=>({getUin:async()=>({uinInfo:new Map([["uid",actualUin]])})})};
  const context={logger:{info(){},warn(){},error(){}},router:{get(){}},core:{selfInfo:{},context:{session}}};
  const url=`http://127.0.0.1:${controlPort}/v1/avsdk/output`;
  const send=async()=>{listener.onInviteActionToAVSDK({},1,"x");await fetch(url,{method:"POST",headers:{Authorization:"Bearer "+process.env.MAIBOT_QQ_CALL_BRIDGE_TOKEN,"Content-Type":"application/json"},body:JSON.stringify({command:20006,value:[1,"uid",[],3,"relation",0,0,0,0,0,true,"denoise"]})}); await new Promise(r=>setTimeout(r,800));};
  try {
    await plugin_init(context);
    fs.writeFileSync(readyFile,"ready"); await send(); assert.equal(accepts,0);
    actualUin="123456789"; fs.unlinkSync(readyFile); await send(); assert.equal(accepts,0);
    fs.writeFileSync(readyFile,"ready"); await send(); assert.equal(accepts,0);
    fs.writeFileSync(armFile,"armed"); await send(); assert.equal(accepts,1);
  } finally {
    await plugin_cleanup(); await new Promise(resolve=>fakeHost.close(resolve));
    for(const key of names){if(old[key]===undefined)delete process.env[key];else process.env[key]=old[key];}
    fs.rmSync(directory,{recursive:true,force:true});
  }
});


test("periodic AVSDK events do not trigger extra logins", async () => {
  const controlPort = await unusedLoopbackPort(), avPort = await unusedLoopbackPort();
  const names = ["MAIBOT_QQ_CALL_BRIDGE_TOKEN", "MAIBOT_QQ_CALL_BRIDGE_PORT", "MAIBOT_QQ_CALL_AV_HOST_PORT"];
  const old = Object.fromEntries(names.map(k => [k, process.env[k]]));
  Object.assign(process.env, {MAIBOT_QQ_CALL_BRIDGE_TOKEN:"test-token-longer-than-thirty-two-bytes", MAIBOT_QQ_CALL_BRIDGE_PORT:String(controlPort), MAIBOT_QQ_CALL_AV_HOST_PORT:String(avPort)});
  let loginPosts=0;
  const fakeHost=http.createServer((req,res)=>{let raw="";req.on("data",v=>raw+=v);req.on("end",()=>{if(JSON.parse(raw).command===1)loginPosts++;res.end("{}");});});
  await new Promise(resolve=>fakeHost.listen(avPort,"127.0.0.1",resolve));
  const service={isNull:()=>false,addKernelAVSDKListener(){return 1;},removeKernelAVSDKListener(){}};
  const session={getAVSDKService:()=>service,getAccountPath:()=>"/tmp/fake"};
  const context={logger:{info(){},warn(){},error(){}},router:{get(){}},core:{selfInfo:{uin:"123456789",uid:"dummy"},context:{session}}};
  try {
    await plugin_init(context);await new Promise(r=>setTimeout(r,850));assert.equal(loginPosts,1);
    const statusUrl=`http://127.0.0.1:${controlPort}/v1/status`;
    const outputUrl=`http://127.0.0.1:${controlPort}/v1/avsdk/output`;
    const headers={Authorization:"Bearer "+process.env.MAIBOT_QQ_CALL_BRIDGE_TOKEN,"Content-Type":"application/json"};
    await fetch(outputUrl,{method:"POST",headers,body:JSON.stringify({command:1,value:[1]})});
    let state=await (await fetch(statusUrl,{headers})).json(); assert.equal(state.data.avHost.loginConfirmed,false);
    await fetch(outputUrl,{method:"POST",headers,body:JSON.stringify({command:1,value:[0]})});
    state=await (await fetch(statusUrl,{headers})).json(); assert.equal(state.data.avHost.loginConfirmed,true);
    for(let i=0;i<10;i++) await fetch(`http://127.0.0.1:${controlPort}/v1/avsdk/output`,{method:"POST",headers:{Authorization:"Bearer "+process.env.MAIBOT_QQ_CALL_BRIDGE_TOKEN,"Content-Type":"application/json"},body:JSON.stringify({command:i%2?20050:120043,value:[]})});
    await new Promise(r=>setTimeout(r,550));assert.equal(loginPosts,1);
  } finally {
    await plugin_cleanup();await new Promise(resolve=>fakeHost.close(resolve));
    for(const key of names){if(old[key]===undefined)delete process.env[key];else process.env[key]=old[key];}
  }
});
