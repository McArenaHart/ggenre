/* Original deterministic rhythm beds. No downloaded samples or external audio service. */
(function (scope) {
  "use strict";
  const SOUNDS={
    piano:{label:"Grand piano",parts:["piano"],attack:.008,release:.05,sustain:.64,gain:.12},
    "bright-piano":{label:"Bright piano",parts:["piano"],attack:.006,release:.06,sustain:.5,gain:.11},
    "electric-piano":{label:"Electric piano",parts:["piano","pad"],attack:.012,release:.14,sustain:.65,gain:.13},
    organ:{label:"Drawbar organ",parts:["piano","pad"],attack:.016,release:.07,sustain:.9,gain:.105},
    "synth-lead":{label:"Classic synth lead",parts:["piano"],attack:.012,release:.09,sustain:.8,gain:.1},
    pluck:{label:"Soft pluck",parts:["piano"],attack:.003,release:.07,sustain:.22,gain:.14},
    strings:{label:"String ensemble",parts:["piano","pad"],attack:.22,release:.28,sustain:.86,gain:.105},
    pad:{label:"Classic synth chords",parts:["pad"],attack:.18,release:.22,sustain:.8,gain:.12},
    "warm-pad":{label:"Warm worship pad",parts:["piano","pad"],attack:.32,release:.45,sustain:.85,gain:.14},
    "airy-pad":{label:"Airy pad",parts:["piano","pad"],attack:.25,release:.35,sustain:.8,gain:.13},
    bass:{label:"Finger bass",parts:["bass"],attack:.012,release:.06,sustain:.7,gain:.22},
    "sub-bass":{label:"Sub bass",parts:["bass"],attack:.018,release:.08,sustain:.9,gain:.25},
    "synth-bass":{label:"Synth bass",parts:["bass"],attack:.012,release:.08,sustain:.8,gain:.18}
  };
  const DRUMS=["kick","snare","hat","clap","rim","tom-low","tom-mid","tom-high"];
  function voice(sound){if(!Object.hasOwn(SOUNDS,sound))throw new Error("Choose a supported instrument sound.");return SOUNDS[sound];}
  function wave(phase,sound){
    switch(sound){
      case "bright-piano":return Math.sin(phase)+.4*Math.sin(phase*2)+.23*Math.sin(phase*3)+.1*Math.sin(phase*4);
      case "electric-piano":return Math.sin(phase+.8*Math.sin(phase*2))+.12*Math.sin(phase*3);
      case "organ":return Math.sin(phase)+.4*Math.sin(phase*2)+.3*Math.sin(phase*3)+.12*Math.sin(phase*4);
      case "synth-lead":return Math.sin(phase)+.48*Math.sin(phase*2)+.3*Math.sin(phase*3)+.18*Math.sin(phase*4)+.09*Math.sin(phase*5);
      case "pluck":return Math.sin(phase)+.3*Math.sin(phase*3)+.12*Math.sin(phase*5);
      case "strings":return Math.sin(phase)+.35*Math.sin(phase*2)+.22*Math.sin(phase*3)+.12*Math.sin(phase*4)+.06*Math.sin(phase*5);
      case "warm-pad":return .65*Math.sin(phase)+.18*Math.sin(phase*63/64)+.18*Math.sin(phase*65/64)+.12*Math.sin(phase*2);
      case "airy-pad":return .65*Math.sin(phase)+.18*Math.sin(phase*65/64)+.15*Math.sin(phase*3)+.08*Math.sin(phase*5);
      case "sub-bass":return Math.sin(phase)+.06*Math.sin(phase*2);
      case "synth-bass":return Math.sin(phase)+.35*Math.sin(phase*2)+.15*Math.sin(phase*3);
      case "bass":return Math.sin(phase)+.18*Math.sin(phase*2);
      case "pad":return Math.sin(phase)+.15*Math.sin(phase*2);
      default:return Math.sin(phase)+.32*Math.sin(phase*2)+.14*Math.sin(phase*3);
    }
  }
  function plan(preset, bpm, bars) {
    if (!preset?.pattern || !Number.isInteger(bpm) || bpm < 40 || bpm > 240 || ![2,4,8,16,32].includes(bars)) throw new Error("Choose a valid tempo and beat length.");
    const step = 60 / bpm / 4, duration = bars * 16 * step, events = [];
    for (let bar = 0; bar < bars; bar++) for (const [instrument, hits] of Object.entries(preset.pattern)) {
      if (!DRUMS.includes(instrument)) throw new Error("Unknown rhythm instrument.");
      for (const hit of hits) {
        if (!Number.isInteger(hit) || hit < 0 || hit > 15) throw new Error("Invalid rhythm pattern.");
        const delay = hit % 4 >= 2 ? Math.min(.4, Math.max(0, preset.swing || 0)) * 2 * step : 0;
        events.push({instrument, time: (bar * 16 + hit) * step + delay});
      }
    }
    if(preset.fill)for(let bar=3;bar<bars;bar+=4)for(const [instrument,hits] of Object.entries(preset.fill)){
      if(!DRUMS.includes(instrument)||!Array.isArray(hits)||hits.some(hit=>!Number.isInteger(hit)||hit<0||hit>15))throw new Error("Invalid drum fill.");
      for(const hit of hits)events.push({instrument,time:(bar*16+hit)*step});
    }
    return {duration, events};
  }
  function drum(context, instrument) {
    if(!DRUMS.includes(instrument))throw new Error("Choose a supported drum sound.");
    const rate = context.sampleRate, length = instrument.startsWith("tom-") ? .5 : instrument === "kick" ? .4 : instrument === "snare" ? .22 : instrument === "clap" ? .18 : .08;
    const buffer = context.createBuffer(1, Math.ceil(rate * length), rate), values = buffer.getChannelData(0);
    let seed = 12345, previous = 0, phase = 0;
    for (let i = 0; i < values.length; i++) {
      const t = i / rate; seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      const noise = seed / 2147483648 - 1, high = noise - previous; previous = noise * .6 + previous * .4;
      if (instrument === "kick") { phase += 2 * Math.PI * (45 + 105 * Math.exp(-t * 32)) / rate; values[i] = Math.sin(phase) * Math.exp(-t * 13) * .8; }
      else if (instrument === "snare") values[i] = (high * .35 + Math.sin(2 * Math.PI * 180 * t) * .12) * Math.exp(-t * 24);
      else if (instrument === "hat") values[i] = high * Math.exp(-t * 78) * .13;
      else if (instrument === "rim") values[i] = (Math.sin(2 * Math.PI * 1600 * t) + Math.sin(2 * Math.PI * 2300 * t)) * Math.exp(-t * 90) * .18;
      else if(instrument.startsWith("tom-")){const frequency={"tom-low":90,"tom-mid":140,"tom-high":210}[instrument];phase+=2*Math.PI*frequency*(1+.6*Math.exp(-t*28))/rate;values[i]=(Math.sin(phase)*.65+noise*.025*Math.exp(-t*35))*Math.min(1,t/.0015)*Math.exp(-t*(instrument==="tom-low"?9:instrument==="tom-mid"?12:15))*Math.min(1,(length-t)/.05);}
      else values[i] = high * .3 * Math.exp(-t * 22) * ((t < .065 && t % .022 < .009) ? 1 : .35);
    }
    return buffer;
  }
  const progressions = {
    major: [[0,4,7],[7,11,14],[9,12,16],[5,9,12]],
    worship: [[0,4,7],[5,9,12],[0,4,7],[7,11,14]],
    soul: [[2,5,9,12],[7,11,14,17],[0,4,7,11],[9,12,16,19]],
    minor: [[0,3,7],[8,12,15],[3,7,10],[10,14,17]]
  };
  const modes = {drums:["drums"],piano:["piano"],bass:["bass"],chords:["pad"],full:["drums","piano","bass","pad"]};
  function pianoArrangement(bpm,bars,options){
    if(!["piano","bass","chords","drums","full"].includes(options.mode)||!Number.isInteger(bpm)||bpm<40||bpm>240||!Number.isInteger(bars)||bars<1||bars>256||bars*240/bpm>300||!Number.isInteger(options.key)||options.key<0||options.key>11||!Array.isArray(options.clips)||options.clips.length>64)throw new Error("Keep the piano song within five minutes and 64 sections.");
    const events=[],spans=[],ids=new Set(),step=60/bpm/4,defaultPart={piano:"piano",bass:"bass",chords:"pad",drums:"drums",full:"piano"}[options.mode],allowed=options.mode==="full"?["piano","bass","pad","drums"]:[defaultPart];
    if(options.sounds&&(typeof options.sounds!=="object"||Array.isArray(options.sounds)||Object.entries(options.sounds).some(([part,sound])=>!["piano","bass","pad"].includes(part)||!Object.hasOwn(SOUNDS,sound)||!SOUNDS[sound].parts.includes(part))))throw new Error("Choose a sound available for each instrument layer.");
    if(options.levels&&(typeof options.levels!=="object"||Array.isArray(options.levels)||Object.entries(options.levels).some(([part,level])=>!["piano","bass","pad","drums"].includes(part)||!Number.isFinite(level)||level<0||level>1)))throw new Error("Invalid instrument volume.");
    for(const clip of options.clips){
      const instrument=clip?.instrument||defaultPart,level=options.levels?.[instrument]??1;
      if(!allowed.includes(instrument))throw new Error("Choose an instrument available in this workspace.");
      if(!clip||typeof clip.id!=="string"||!clip.id.length||clip.id.length>64||ids.has(clip.id)||typeof clip.name!=="string"||!clip.name.trim()||clip.name.length>80||!Number.isInteger(clip.start)||clip.start<0||!Number.isInteger(clip.bars)||clip.bars<1||clip.bars>32||clip.start+clip.bars>bars||!Array.isArray(clip.notes)||clip.notes.length>1024||spans.some(([start,end,part])=>part===instrument&&clip.start<end&&clip.start+clip.bars>start))throw new Error("Keep named sections inside the song without overlapping.");
      ids.add(clip.id);spans.push([clip.start,clip.start+clip.bars,instrument]);const occupied=new Set();
      for(const note of clip.notes){
        if(!Number.isInteger(note.step)||note.step<0||!Number.isInteger(note.length)||note.length<1||note.length>64||note.step+note.length>clip.bars*16||!Number.isInteger(note.midi)||note.midi<24||note.midi>84||note.midi+options.key>96||occupied.has(`${note.step}:${note.midi}`)||!Number.isFinite(note.velocity??.7)||(note.velocity??.7)<=0||(note.velocity??.7)>1)throw new Error("Invalid piano note.");
        occupied.add(`${note.step}:${note.midi}`);
        if(instrument==="drums"){
          const drum={24:"kick",26:"snare",28:"hat",29:"clap",31:"rim",32:"tom-low",33:"tom-mid",34:"tom-high"}[note.midi];if(!drum||note.length!==1)throw new Error("Choose a valid drum step.");events.push({instrument:drum,time:(clip.start*16+note.step)*step,level:level*(note.velocity??.7)});
        }else events.push({instrument,sound:options.sounds?.[instrument]||instrument,midi:note.midi+options.key,time:(clip.start*16+note.step)*step,duration:note.length*step,velocity:note.velocity??.7,level});
        if(events.length>4096)throw new Error("Use up to 4096 piano notes per song.");
      }
    }
    return {duration:bars*240/bpm,events};
  }
  function arrangement(preset,bpm,bars,options={}) {
    if(options.schema===2)return pianoArrangement(bpm,bars,options);
    const rhythm=plan(preset,bpm,bars),mode=options.mode || "drums",key=options.key ?? 0,progression=options.progression || "major";
    if(!Object.hasOwn(modes,mode)||!Number.isInteger(key)||key<0||key>11||!Object.hasOwn(progressions,progression)) throw new Error("Choose a valid instrument, key and chord progression.");
    const enabled=modes[mode],events=enabled.includes("drums")?rhythm.events.slice():[],beat=60/bpm;
    for(let bar=0;bar<bars;bar++) {
      const chord=progressions[progression][bar%4],at=bar*4*beat;
      if(enabled.includes("piano")) {
        for(const pulse of [0,1.5,2.5]) for(const interval of chord) events.push({instrument:"piano",midi:60+key+interval,time:at+pulse*beat,duration:Math.min(1.3,4-pulse)*beat,velocity:pulse===0?.7:.48});
      }
      if(enabled.includes("bass")) for(const [pulse,interval] of [[0,chord[0]],[1.5,chord[0]],[2,chord[0]+7],[3,chord[0]]]) events.push({instrument:"bass",midi:36+key+interval,time:at+pulse*beat,duration:(pulse===1.5?.45:.8)*beat,velocity:.8});
      if(enabled.includes("pad")) for(const interval of chord) events.push({instrument:"pad",midi:48+key+interval,time:at,duration:4*beat,velocity:.42});
    }
    if(options.notes !== undefined) {
      if(!options.notes || typeof options.notes !== "object" || Array.isArray(options.notes)) throw new Error("Invalid note pattern.");
      for(const [part,notes] of Object.entries(options.notes)) {
        if(!["piano","bass","pad"].includes(part)||!Array.isArray(notes)||notes.length>256) throw new Error("Invalid note pattern.");
        const seen=new Set();
        for(const note of notes) {
          if(!Number.isInteger(note.step)||note.step<0||note.step>63||!Number.isInteger(note.length)||note.length<1||note.length>16||note.step+note.length>64||!Number.isInteger(note.midi)||note.midi<24||note.midi>84||note.midi+key>96||seen.has(`${note.step}:${note.midi}`)) throw new Error("Invalid note position, pitch or length.");
          seen.add(`${note.step}:${note.midi}`);
        }
        if(!enabled.includes(part)) continue;
        for(let i=events.length-1;i>=0;i--) if(events[i].instrument===part) events.splice(i,1);
        for(let cycle=0;cycle<bars/4;cycle++) for(const note of notes) if((cycle*64+note.step)*beat/4<rhythm.duration) events.push({instrument:part,midi:note.midi+key,time:(cycle*64+note.step)*beat/4,duration:Math.min(note.length*beat/4,rhythm.duration-(cycle*64+note.step)*beat/4),velocity:part==="bass"?.8:part==="pad"?.42:.7});
      }
    }
    if(options.drums !== undefined) {
      if(!options.drums || typeof options.drums!=="object"||Array.isArray(options.drums)) throw new Error("Invalid drum pattern.");
      for(const [part,hits] of Object.entries(options.drums)) if(!DRUMS.includes(part)||!Array.isArray(hits)||hits.length>64||new Set(hits).size!==hits.length||hits.some(step=>!Number.isInteger(step)||step<0||step>63)) throw new Error("Invalid drum steps.");
      if(enabled.includes("drums")) {
        for(let i=events.length-1;i>=0;i--) if(events[i].midi===undefined) events.splice(i,1);
        for(let cycle=0;cycle<bars/4;cycle++) for(const [instrument,hits] of Object.entries(options.drums)) for(const step of hits) if((cycle*64+step)*beat/4<rhythm.duration) events.push({instrument,time:(cycle*64+step)*beat/4});
      }
    }
    const levels=options.levels || {};
    if(typeof levels!=="object"||Array.isArray(levels)||Object.entries(levels).some(([part,level])=>!["drums","piano","bass","pad"].includes(part)||!Number.isFinite(level)||level<0||level>1)) throw new Error("Invalid instrument volume.");
    for(const event of events) event.level=levels[event.midi===undefined?"drums":event.instrument] ?? 1;
    return {duration:rhythm.duration,events};
  }
  function pattern(preset,bpm,options={}) {
    const schedule=arrangement(preset,bpm,4,{mode:"full",key:0,progression:options.progression||"major"});
    const notes={piano:[],bass:[],pad:[]},drums={kick:[],snare:[],hat:[],clap:[],rim:[],"tom-low":[],"tom-mid":[],"tom-high":[]},step=60/bpm/4;
    for(const event of schedule.events) {
      const position=Math.round(event.time/step);
      if(event.midi===undefined) drums[event.instrument].push(position);
      else notes[event.instrument].push({step:position,midi:event.midi,length:Math.min(16,64-position,Math.max(1,Math.round(event.duration/step)))});
    }
    return {notes,drums};
  }
  function pitched(context,instrument,midi,duration,velocity=1,sustain=false,sound=instrument) {
    if(!["piano","bass","pad"].includes(instrument)||!Number.isInteger(midi)||midi<24||midi>96||!Number.isFinite(duration)||duration<=0||duration>30||!Number.isFinite(velocity)||velocity<0||velocity>1) throw new Error("Invalid instrument note.");
    const profile=voice(sound);if(!profile.parts.includes(instrument))throw new Error("This sound is unavailable for the instrument layer.");
    const rate=context.sampleRate,buffer=context.createBuffer(1,Math.ceil(duration*rate),rate),values=buffer.getChannelData(0),frequency=440*2**((midi-69)/12);
    for(let i=0;i<values.length;i++) {
      const t=i/rate,phase=2*Math.PI*frequency*t,release=Math.min(1,(duration-t)/Math.min(.12,duration/4));
      let wave,envelope;
      if(instrument==="piano") {wave=Math.sin(phase)+.32*Math.sin(phase*2)*Math.exp(-t*3)+.14*Math.sin(phase*3.003)*Math.exp(-t*5);envelope=sustain?Math.min(1,t/.008)*(.55+.45*Math.exp(-t*8)):Math.min(1,t/.004)*Math.exp(-t*2.7);}
      else if(instrument==="bass") {wave=Math.sin(phase)+.24*Math.sin(phase*2)+.08*Math.sin(phase*3);envelope=Math.min(1,t/.012)*(sustain?(.7+.3*Math.exp(-t*3)):Math.exp(-t*.9));}
      else {wave=Math.sin(phase)+.18*Math.sin(phase*1.003)+.12*Math.sin(phase*2);envelope=Math.min(1,t/.18)*Math.min(1,(duration-t)/.22);}
      if(sound!==instrument){
        const shape=api.wave(phase,sound),attack=Math.min(1,t/profile.attack),body=profile.sustain+(1-profile.sustain)*Math.exp(-t*(sound==="pluck"?12:4)),fade=Math.min(1,(duration-t)/Math.min(profile.release,duration/4));
        values[i]=shape*attack*body*Math.max(0,fade)*velocity*profile.gain;
      }else values[i]=wave*envelope*Math.max(0,release)*velocity*(instrument==="bass"?.28:.12);
    }
    return buffer;
  }
  async function render(preset, bpm, bars, options = {}) {
    const schedule = arrangement(preset, bpm, bars, options), context = new OfflineAudioContext(2, Math.ceil(schedule.duration * 44100), 44100), buffers = new Map();
    if(options.schema===2){
      const output=context.createBuffer(2,Math.ceil(schedule.duration*44100),44100),mono=output.getChannelData(0);
      for(const [index,event] of schedule.events.entries()){
        const key=event.midi===undefined?event.instrument:`${event.instrument}:${event.sound||event.instrument}:${event.midi}:${event.duration}:${event.velocity}`;
        if(!buffers.has(key))buffers.set(key,event.midi===undefined?drum(context,event.instrument):pitched(context,event.instrument,event.midi,event.duration,event.velocity,true,event.sound||event.instrument));
        const samples=buffers.get(key).getChannelData(0),at=Math.round(event.time*44100),length=Math.min(samples.length,mono.length-at),gain=.75*event.level;
        for(let frame=0;frame<length;frame++)mono[at+frame]+=samples[frame]*gain;
        if(index%32===0){options.onProgress?.(Math.round((index+1)/Math.max(1,schedule.events.length)*100));await new Promise(resolve=>setTimeout(resolve,0));}
      }
      let peak=0;for(const value of mono)peak=Math.max(peak,Math.abs(value));if(peak>.9)for(let i=0;i<mono.length;i++)mono[i]*=.9/peak;
      output.getChannelData(1).set(mono);options.onProgress?.(100);return output;
    }
    const master = context.createGain(); master.gain.value = .75; master.connect(context.destination);
    for (const event of schedule.events) {
      const key = event.midi === undefined ? event.instrument : `${event.instrument}:${event.sound||event.instrument}:${event.midi}:${event.duration}:${event.velocity}`;
      if (!buffers.has(key)) buffers.set(key, event.midi === undefined ? drum(context,event.instrument) : pitched(context,event.instrument,event.midi,event.duration,event.velocity,options.schema===2,event.sound||event.instrument));
      const source = context.createBufferSource(); source.buffer = buffers.get(key); const volume=context.createGain(); volume.gain.value=event.level; source.connect(volume); volume.connect(master); source.start(event.time);
    }
    const output = await context.startRendering();
    let peak = 0; for (let c = 0; c < output.numberOfChannels; c++) for (const value of output.getChannelData(c)) peak = Math.max(peak, Math.abs(value));
    if (peak > .9) for (let c = 0; c < output.numberOfChannels; c++) { const data = output.getChannelData(c); for (let i = 0; i < data.length; i++) data[i] *= .9 / peak; }
    return output;
  }
  const api = {SOUNDS, DRUMS, voice, wave, plan, drum, arrangement, pianoArrangement, pattern, pitched, render};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else scope.StudioBeats = api;
})(typeof window !== "undefined" ? window : globalThis);
