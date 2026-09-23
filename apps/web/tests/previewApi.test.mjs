import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const html = readFileSync(new URL('../public/design-v2/index.html', import.meta.url), 'utf8');
const functions = html.slice(html.indexOf('    async function executeSnowfall()'), html.indexOf("    document.getElementById('metricSelect').addEventListener"));

test('preview sends canonical V2 requests and reads city-level series without duplicate runs', async () => {
  const calls = [];
  let uuid = 0;
  const context = vm.createContext({
    state:{ scenario:'snowfall' }, snowfallTask:null, renderAll(){}, crypto:{ randomUUID:() => `key-${++uuid}` },
    async apiRequest(path, payload, key) {
      calls.push({path,payload,key});
      if (path === '/v2/health') return {status:'ok'};
      if (path === '/scenarios') return {id:'scenario-1'};
      if (path === '/runs') return {runId:'run-1',stateVersion:0};
      if (path.endsWith('/commands')) return {accepted:true};
      if (path === '/runs/run-1') return {runId:'run-1',simMinute:360,status:'completed',pendingCommand:false};
      if (path.endsWith('/metrics')) return {series:[
        {metricId:'travel-time-p90',groupBy:{districtId:'nura'},points:[{value:99}]},
        ...[['travel-time-p90',42],['backlog',12],['service-unavailability-hours',3]].map(([metricId,value]) => ({metricId,groupBy:{districtId:null},points:[{value}]})),
      ]};
      throw new Error(path);
    },
  });
  vm.runInContext(functions, context);
  await Promise.all([context.runSnowfall(),context.runSnowfall()]);
  await context.runSnowfall();
  const run = calls.find(call => call.path === '/runs');
  assert.equal(run.payload.scenarioId,'scenario-1');
  assert.equal(run.payload.horizon,360);
  assert.equal(run.key,'key-1');
  const command = calls.find(call => call.path.endsWith('/commands'));
  assert.equal(command.payload.type,'clock.step');
  assert.equal(command.payload.payload.minutes,360);
  assert.equal(command.payload.expectedStateVersion,0);
  assert.equal(command.key,command.payload.idempotencyKey);
  assert.equal(calls.filter(call => call.path === '/runs').length,1);
  assert.match(context.state.snowfallCaption,/42\.0 мин/);
  assert.equal(context.state.snowfallComplete,true);
});

test('unavailable worker is an explicit error and never starts a fake run', async () => {
  const context = vm.createContext({
    state:{scenario:'snowfall'},snowfallTask:null,renderAll(){},
    apiRequest:async path => { assert.equal(path,'/v2/health'); return {status:'worker-unavailable'}; },
  });
  vm.runInContext(functions,context);
  await context.runSnowfall();
  assert.match(context.state.snowfallCaption,/Ошибка V2: Worker/);
  assert.equal(context.state.snowfallComplete,undefined);
});
