const test = require("node:test");
const assert = require("node:assert/strict");
const {plan, drum} = require("../static/js/studio-beats.js");
const preset = {swing:.12,pattern:{kick:[0,8],snare:[4,12],hat:[0,2,4,6,8,10,12,14]}};
test("standard beats use predictable bar length and repeat their pattern",()=>{
 const result=plan(preset,120,8);
 assert.equal(result.duration,16);assert.equal(result.events.filter(event=>event.instrument==="kick").length,16);
 assert.ok(result.events.every(event=>event.time>=0&&event.time<result.duration));
 assert.deepEqual(plan(preset,120,8),result);
});
test("swing moves off-beat hats without changing bar duration",()=>{
 const straight=plan({...preset,swing:0},120,4),swung=plan(preset,120,4);
 assert.equal(straight.duration,swung.duration);
 assert.ok(swung.events.find(event=>event.instrument==="hat"&&event.time>0).time>straight.events.find(event=>event.instrument==="hat"&&event.time>0).time);
});
test("invalid beat parameters and instruments are rejected",()=>{
 for(const bpm of [0,39,241,NaN])assert.throws(()=>plan(preset,bpm,8));
 assert.throws(()=>plan(preset,120,5));assert.throws(()=>plan({pattern:{unknown:[0]}},120,8));
 assert.throws(()=>plan({pattern:{kick:[17]}},120,8));
});
test("all synthesized drums are deterministic, finite, bounded and audible",()=>{
 const context={sampleRate:44100,createBuffer(channels,length){const data=new Float32Array(length);return {getChannelData:()=>data};}};
 for(const instrument of ["kick","snare","hat","clap","rim"]){
  const a=drum(context,instrument).getChannelData(0),b=drum(context,instrument).getChannelData(0);
  assert.deepEqual(a,b);assert.ok(a.every(value=>Number.isFinite(value)&&Math.abs(value)<=1));assert.ok(a.some(value=>Math.abs(value)>.01));
 }
});
const {arrangement,pitched,render}=require('../static/js/studio-beats.js');
test('instrument arrangements contain the chosen parts and transpose every pitched note',()=>{
 for(const mode of ['drums','piano','bass','chords','full']) {
  const a=arrangement(preset,90,8,{mode,key:0,progression:'soul'}),b=arrangement(preset,90,8,{mode,key:5,progression:'soul'});
  assert.equal(a.duration,32*60/90);assert.equal(a.events.length,b.events.length);
  a.events.forEach((e,i)=>{assert.ok(e.time>=0&&e.time<a.duration);if(e.midi!==undefined){assert.equal(b.events[i].midi,e.midi+5);assert.ok(e.time+e.duration<=a.duration+1e-9);}});
  const instruments=new Set(a.events.map(e=>e.instrument));
  if(mode==='full')for(const instrument of ['kick','piano','bass','pad'])assert.ok(instruments.has(instrument));
  else if(mode!=='drums')assert.deepEqual([...instruments],[mode==='chords'?'pad':mode]);
 }
});
test('all chord progressions fit bounds at extreme tempos and keys',()=>{
 for(const progression of ['major','worship','soul','minor'])for(const key of [0,11])for(const bpm of [40,240]) {
 const a=arrangement(preset,bpm,32,{mode:'full',key,progression});assert.ok(a.duration<=300);
 assert.ok(a.events.every(e=>e.midi===undefined||e.midi>=24&&e.midi<=96));
 }
 for(const options of [{mode:'bad'},{key:12},{key:NaN},{progression:'toString'}])assert.throws(()=>arrangement(preset,90,8,options));
});
test('piano bass and pad synthesis are audible finite and fade out',()=>{
 const ctx={sampleRate:44100,createBuffer(c,n){const data=new Float32Array(n);return {getChannelData:()=>data}}};
 for(const instrument of ['piano','bass','pad']){
 const a=pitched(ctx,instrument,60,1,.7).getChannelData(0);assert.ok(a.every(v=>Number.isFinite(v)&&Math.abs(v)<=1));assert.ok(a.some(v=>Math.abs(v)>.01));assert.ok(Math.abs(a[a.length-1])<.001);assert.equal(a[0],0);
 assert.deepEqual(a,pitched(ctx,instrument,60,1,.7).getChannelData(0));
 }
 assert.throws(()=>pitched(ctx,'bad',60,1));assert.throws(()=>pitched(ctx,'piano',60,NaN));
});
test('render schedules full backing and peak limits the output',async()=>{
 const scheduled=[];const output=[Float32Array.from([2,-2]),Float32Array.from([1,-1])];
 global.OfflineAudioContext=class{constructor(c,n,r){this.sampleRate=r;}createBuffer(c,n){const data=new Float32Array(n);return{getChannelData:()=>data}}createGain(){return{gain:{},connect(){}}}createBufferSource(){return{connect(){},start(t){scheduled.push(t)}}}async startRendering(){return{numberOfChannels:2,getChannelData:c=>output[c]}}};
 try{const result=await render(preset,120,4,{mode:'full',key:2,progression:'minor'});assert.equal(scheduled.length,arrangement(preset,120,4,{mode:'full',key:2,progression:'minor'}).events.length);assert.ok(Math.abs(result.getChannelData(0)[0]-.9)<1e-6);}finally{delete global.OfflineAudioContext;}
});
