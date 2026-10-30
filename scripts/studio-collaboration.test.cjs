const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const {mixSettings,countdown}=require('../static/js/studio-collaboration.js');
test('collaboration mix accepts bounded numeric settings and rejects invalid values',()=>{
  assert.deepEqual(mixSettings('1','.5','-50'),{original_gain:1,vocal_gain:.5,shift_ms:-50});
  for(const values of [[NaN,1,0],[1,3,0],[1,1,1001],[-1,1,0]])assert.throws(()=>mixSettings(...values));
});
function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve};}
function harness(options={}){
  const elements={},windowEvents={},documentEvents={},calls={permission:0,stopped:0,cancelled:0,posted:[]};
  function element(id){return elements[id]??={id,value:({'collab-original':'1','collab-level':'1','collab-shift':'0','collab-role':'Harmony'})[id]||'',hidden:false,disabled:false,events:{},addEventListener(name,handler){this.events[name]=handler;},pause(){},play(){return Promise.resolve();}};}
  const root=element('collaboration');root.dataset={save:'/save/',audio:'/guide/',request:'test-id'};root.querySelector=()=>({value:'csrf'});
  const stream={getTracks:()=>[{stop:()=>calls.stopped++}]};
  class Context{constructor(){this.currentTime=0;}resume(){return Promise.resolve();}decodeAudioData(){return Promise.resolve({duration:2});}close(){}}
  let done;
  const sandbox={console,Blob,Float32Array,Number,Math,Object,Error,Promise,URL:{createObjectURL:()=>'/blob/',revokeObjectURL(){}},crypto:{randomUUID:()=>String(Math.random())},FormData:class{constructor(){this.data={};}append(k,v){this.data[k]=v;}},AudioContext:Context,navigator:{mediaDevices:{getUserMedia:async()=>{calls.permission++;return options.permission?await options.permission:stream;}}},document:{hidden:false,getElementById:element,addEventListener:(name,handler)=>documentEvents[name]=handler},addEventListener:(name,handler)=>windowEvents[name]=handler,requestAnimationFrame:()=>1,cancelAnimationFrame(){},fetch:async(url,args)=>{if(args){calls.posted.push(args);return{ok:true,json:async()=>({preview:'/preview/',publish:'/publish/'})};}if(options.guide)await options.guide;return{ok:true,arrayBuffer:async()=>new ArrayBuffer(0)};},StudioComposer:{wav:()=>new Blob(['wav'])},StudioAudio:{estimatedDelay:()=>0,compensate:s=>s,begin:async args=>{done=args.onDone;return{startTime:0,cancel(){calls.cancelled++;},stop(){done({samples:new Float32Array(44100),sampleRate:44100});}};}}};
  sandbox.window=sandbox;
  vm.runInNewContext(fs.readFileSync('static/js/studio-collaboration.js','utf8'),sandbox);
  return{elements,calls,stream,windowEvents,documentEvents,sandbox,click:id=>element(id).events.click(),done:()=>done({samples:new Float32Array(44100),sampleRate:44100})};
}
test('collaboration does not request microphone permission on load',()=>{const h=harness();assert.equal(h.calls.permission,0);assert.equal(h.elements['collaboration'].dataset.state,'idle');});
test('cancel during guide preparation never opens microphone',async()=>{const wait=deferred(),h=harness({guide:wait.promise});const pending=h.click('collab-record');await Promise.resolve();h.click('collab-cancel');wait.resolve();await pending;assert.equal(h.calls.permission,0);assert.equal(h.elements.collaboration.dataset.state,'idle');});
test('cancel during pending permission stops the late stream',async()=>{const permission=deferred(),h=harness({permission:permission.promise});const pending=h.click('collab-record');await new Promise(setImmediate);assert.equal(h.calls.permission,1);h.click('collab-cancel');permission.resolve(h.stream);await pending;assert.equal(h.calls.stopped,1);assert.equal(h.calls.cancelled,0);assert.equal(h.elements.collaboration.dataset.state,'idle');});
test('stop produces review, preview posts once, and changing mix hides stale result',async()=>{const h=harness();await h.click('collab-record');assert.equal(h.elements.collaboration.dataset.state,'recording');h.click('collab-stop');assert.equal(h.elements.collaboration.dataset.state,'review');await h.click('collab-render');assert.equal(h.calls.posted.length,1);assert.equal(h.calls.posted[0].headers['X-CSRFToken'],'csrf');assert.equal(h.elements['collab-publish'].action,'/publish/');assert.equal(h.elements['collab-result'].hidden,false);h.elements['collab-level'].events.change();assert.equal(h.elements['collab-result'].hidden,true);});
test('cancel and backgrounding release capture without publishing',async()=>{const h=harness();await h.click('collab-record');h.sandbox.document.hidden=true;h.documentEvents.visibilitychange();assert.equal(h.calls.cancelled,1);assert.equal(h.calls.posted.length,0);assert.equal(h.elements.collaboration.dataset.state,'idle');});

test('four-beat countdown excludes the recorder preparation lead-in',()=>{assert.equal(countdown(3.25),4);assert.equal(countdown(2.2),3);assert.equal(countdown(.2),1);});
