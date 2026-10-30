const test=require('node:test'),assert=require('node:assert/strict');
const {toggleNote,wav}=require('../static/js/studio-composer.js');
const {pattern,arrangement}=require('../static/js/studio-beats.js');
const preset={pattern:{kick:[0,8],snare:[4,12]},swing:0};
test('piano roll toggles sustained notes without mutating source pattern',()=>{const notes=[{step:0,midi:60,length:8}];assert.deepEqual(toggleNote(notes,4,60,4),[]);assert.equal(notes.length,1);const added=toggleNote(notes,63,64,16);assert.deepEqual(added[1],{step:63,midi:64,length:1});});
test('generated editable patterns preserve every instrument across four bars',()=>{const p=pattern(preset,90,{progression:'soul'});for(const part of ['piano','bass','pad'])assert.ok(p.notes[part].length>0);assert.equal(p.drums.kick.length,8);const a=arrangement(preset,90,8,{mode:'full',key:2,notes:p.notes,drums:p.drums,levels:{bass:0}});assert.ok(a.events.filter(e=>e.instrument==='bass').every(e=>e.level===0));assert.equal(a.events.filter(e=>e.instrument==='piano').length,p.notes.piano.length*2);assert.ok(a.events.find(e=>e.instrument==='piano').midi===p.notes.piano[0].midi+2);});
test('blank patterns stay blank instead of regenerating default notes',()=>{const a=arrangement(preset,90,4,{mode:'full',notes:{piano:[],bass:[],pad:[]},drums:{}});assert.equal(a.events.length,0);});
test('custom patterns reject invalid and duplicate note events',()=>{for(const notes of [[{step:63,midi:60,length:2}],[{step:0,midi:60,length:4},{step:0,midi:60,length:4}],[{step:0,midi:NaN,length:1}]])assert.throws(()=>arrangement(preset,90,4,{mode:'piano',notes:{piano:notes}}));assert.throws(()=>arrangement(preset,90,4,{mode:'full',drums:{kick:[0,0]}}));});
test('rendered composition WAV has interleaved stereo PCM header',async()=>{const blob=wav({numberOfChannels:2,length:2,sampleRate:44100,getChannelData:c=>Float32Array.from(c?[.5,-.5]:[1,-1])});const data=new DataView(await blob.arrayBuffer());assert.equal(data.getUint16(22,true),2);assert.equal(data.getUint32(24,true),44100);assert.equal(data.getUint32(40,true),8);assert.equal(data.getInt16(44,true),32767);assert.equal(data.getInt16(46,true),16384);assert.equal(data.getInt16(48,true),-32768);});

test('overlapping note starts can be removed independently',()=>{const notes=[{step:6,midi:60,length:5},{step:10,midi:60,length:5}];assert.deepEqual(toggleNote(notes,10,60,4),[notes[0]]);});


const {createAuditioner}=require('../static/js/studio-composer.js');
function auditionHarness(resume=async()=>{}){
 const calls=[],sources=[],gains=[];let created=0;
 const ctx={destination:{},resume,close:async()=>{},createBufferSource(){const source={connect(){},start(){this.started=true;},stop(){this.stopped=true;},disconnect(){this.disconnected=true;}};sources.push(source);return source;},createGain(){const gain={gain:{},connect(){},disconnect(){this.disconnected=true;}};gains.push(gain);return gain;}};
 const beats={pitched(...args){calls.push(args.slice(1));return {};},drum(...args){calls.push(args.slice(1));return {};}};
 const audition=createAuditioner(beats,()=>{created++;return ctx;});return{audition,calls,sources,gains,created:()=>created};
}
test('click audition uses selected instrument key length and volume',async()=>{const h=auditionHarness();assert.equal(h.created(),0);await h.audition.play({part:'piano',midi:60,key:2,bpm:120,length:4,level:.5});assert.deepEqual(h.calls[0],['piano',62,.5,.7]);assert.equal(h.gains[0].gain.value,.3);assert.equal(h.sources[0].started,true);h.sources[0].onended();assert.equal(h.sources[0].disconnected,true);assert.equal(h.gains[0].disconnected,true);});
test('drums audition directly and muted parts remain silent',async()=>{const h=auditionHarness();assert.equal(await h.audition.play({part:'bass',midi:36,level:0}),false);assert.equal(h.created(),0);await h.audition.play({part:'kick'});assert.deepEqual(h.calls[0],['kick']);h.audition.stop();assert.equal(h.sources[0].stopped,true);});
test('Stop cancels pending audio activation before a note can sound',async()=>{let resume;const h=auditionHarness(()=>new Promise(resolve=>resume=resolve));const pending=h.audition.play({part:'pad',midi:48,length:16});h.audition.stop();resume();assert.equal(await pending,null);assert.equal(h.sources.length,0);});
test('rapid clicks cap simultaneous audition voices and clean up on close',async()=>{const h=auditionHarness();for(let i=0;i<12;i++)await h.audition.play({part:'piano',midi:60+i});assert.equal(h.created(),1);assert.equal(h.sources.filter(s=>s.stopped).length,4);h.audition.close();assert.ok(h.sources.every(s=>s.disconnected));});
