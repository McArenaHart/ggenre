/* Private editable composition workspace; four-bar piano rolls and drum sequencer. */
(function(scope){
 "use strict";
 function toggleNote(notes,step,midi,length){
  const covering=notes.find(note=>note.midi===midi&&note.step===step)||notes.find(note=>note.midi===midi&&note.step<step&&note.step+note.length>step);
  if(covering)return notes.filter(note=>note!==covering);
  const bounded=Math.min(length,64-step);
  return [...notes.filter(note=>note.midi!==midi||note.step>=step+bounded||note.step+note.length<=step),{step,midi,length:bounded}];
 }
 function wav(buffer){
  const channels=buffer.numberOfChannels,length=buffer.length,data=new ArrayBuffer(44+length*channels*2),view=new DataView(data);
  const text=(at,value)=>{for(let i=0;i<value.length;i++)view.setUint8(at+i,value.charCodeAt(i));};
  text(0,"RIFF");view.setUint32(4,data.byteLength-8,true);text(8,"WAVE");text(12,"fmt ");view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,channels,true);view.setUint32(24,buffer.sampleRate,true);view.setUint32(28,buffer.sampleRate*channels*2,true);view.setUint16(32,channels*2,true);view.setUint16(34,16,true);text(36,"data");view.setUint32(40,length*channels*2,true);
  const samples=Array.from({length:channels},(_,c)=>buffer.getChannelData(c));let position=44;
  for(let i=0;i<length;i++)for(let c=0;c<channels;c++){const value=Math.max(-1,Math.min(1,samples[c][i]));if(!Number.isFinite(value))throw new Error("Invalid rendered audio.");view.setInt16(position,Math.round(value*(value<0?32768:32767)),true);position+=2;}
  return new Blob([data],{type:"audio/wav"});
 }
 function createAuditioner(beats,makeContext){
  let context,epoch=0;const voices=new Set();
  function stop(){epoch++;for(const voice of [...voices])voice.finish(true);}
  async function play({part,midi,length=4,bpm=90,key=0,level=1,sound=part}){
   if(!["piano","bass","pad","kick","snare","hat","clap","rim","tom-low","tom-mid","tom-high"].includes(part)||!Number.isFinite(level)||level<0||level>1||!Number.isInteger(key)||key<0||key>11||!Number.isInteger(length)||length<1||length>16||!Number.isFinite(bpm)||bpm<40||bpm>240)throw new Error("Choose a valid note and instrument level.");
   if(["piano","bass","pad"].includes(part)&&(!Number.isInteger(midi)||midi<24||midi+key>96))throw new Error("Choose a note within the instrument range.");
   if(level===0)return false;
   context=context||makeContext();const token=epoch;await context.resume();if(token!==epoch)return null;
   const buffer=["piano","bass","pad"].includes(part)?(sound===part?beats.pitched(context,part,midi+key,Math.min(1.5,length*60/bpm/4),part==="bass"?.8:part==="pad"?.42:.7):beats.pitched(context,part,midi+key,Math.min(1.5,length*60/bpm/4),part==="bass"?.8:part==="pad"?.42:.7,true,sound)):beats.drum(context,part);
   while(voices.size>=8)voices.values().next().value.finish(true);
   const source=context.createBufferSource(),gain=context.createGain();source.buffer=buffer;gain.gain.value=.6*level;source.connect(gain);gain.connect(context.destination);
   const voice={finish(cancel=false){if(!voices.delete(voice))return;source.onended=null;if(cancel)try{source.stop();}catch(_){}source.disconnect();gain.disconnect();}};
   source.onended=()=>voice.finish();voices.add(voice);
   try{source.start();}catch(error){voice.finish(true);throw error;}
   return true;
  }
  function close(){stop();if(context){const closing=context.close();closing?.catch?.(()=>{});context=null;}}
  return {play,stop,close};
 }
 const api={toggleNote,wav,createAuditioner};if(typeof module!=="undefined"&&module.exports){module.exports=api;return;}scope.StudioComposer=api;
 const root=document.getElementById("composer");if(!root)return;
 const $=id=>document.getElementById(id),presets=JSON.parse($("composer-presets").textContent);
 let config=JSON.parse($("composer-config").textContent),id=root.dataset.id,revision=root.dataset.revision||"",part=config.mode==="bass"?"bass":config.mode==="chords"?"pad":config.mode==="drums"?"drums":"piano",dirty=!id,busy=false,url;
 const names={piano:"Piano",bass:"Bass",pad:"Chords",drums:"Drums"},pitchNames=["C","C♯","D","D♯","E","F","F♯","G","G♯","A","A♯","B"];
 const modes={full:["drums","piano","bass","pad"],piano:["piano"],bass:["bass"],chords:["pad"],drums:["drums"]};
 const status=text=>$("composer-status").textContent=text;
 const auditioner=createAuditioner(StudioBeats,()=>{const Audio=scope.AudioContext||scope.webkitAudioContext;if(!Audio)throw new Error("This browser does not support note audition. Try a current audio-capable browser.");return new Audio({latencyHint:"interactive"});});
 function hear(row,length){
  $("composer-player").pause();const instrument=part==="drums"?row:part,level=config.levels[part]??1,name=part==="drums"?row:names[part]+" "+pitchNames[(row+config.key)%12]+String(Math.floor((row+config.key)/12)-1);
  auditioner.play({part:instrument,midi:part==="drums"?undefined:row,length,bpm:config.bpm,key:config.key,level}).then(played=>{if(played===null)return;status(played?`Auditioning ${name}. Preview plays the whole progression.`:"This instrument is muted. Raise its level to hear notes.");}).catch(error=>status("Note audition unavailable: "+error.message));
 }
 const draftKey=()=>`ggenre-compose:${root.dataset.user}:${id||"new-"+root.dataset.mode}`;
 root.dataset.mode=config.mode;
 const preset=()=>presets.find(p=>p.id===config.preset);
 function defaults(){const pattern=StudioBeats.pattern(preset(),config.bpm,config);config.notes={...pattern.notes,...config.notes};if(!config.drums)config.drums=pattern.drums;config.levels=config.levels||{};}
 defaults();
 function syncSelect(input,value){input.value=String(value);input.dispatchEvent(new Event("change",{bubbles:true}));}
 function fillStyles(){const select=$("composition-style"),category=$("composition-category").value;select.replaceChildren();for(const item of presets.filter(p=>p.category===category)){const option=document.createElement("option");option.value=item.id;option.textContent=item.name;select.append(option);}if(!presets.some(p=>p.id===config.preset&&p.category===category))config.preset=select.options[0].value;select.value=config.preset;}
 function persist(){try{localStorage.setItem(draftKey(),JSON.stringify({revision,config,title:$("composition-title").value,category:$("composition-category").value}));}catch(_){status("Browser recovery unavailable. Save your instrumental to keep it.");}}
 function changed(){dirty=true;$("composer-player").pause();$("composer-use").disabled=true;$("composer-state").textContent="Unsaved changes";persist();}
 function draw(){
  if(!modes[config.mode].includes(part)){part=modes[config.mode][0];syncSelect($("composer-octave"),part==="bass"?36:part==="pad"?48:60);syncSelect($("composer-length"),part==="pad"?16:4);}
  $("workspace-heading").textContent=(config.mode==="full"?"Full arrangement":names[part])+" workspace";
  const tabs=$("composer-parts");tabs.replaceChildren();
  for(const instrument of modes[config.mode]){const button=document.createElement("button");button.type="button";button.textContent=names[instrument];button.className="studio-button "+(part===instrument?"studio-primary":"studio-outline");button.setAttribute("aria-pressed",String(part===instrument));button.addEventListener("click",()=>{part=instrument;syncSelect($("composer-octave"),part==="bass"?36:part==="pad"?48:60);draw();});tabs.append(button);}
  const isDrums=part==="drums",bar=Number($("composer-bar").value),base=Number($("composer-octave").value);
  $("composer-octave-label").hidden=isDrums;$("composer-length-label").hidden=isDrums;
  const grid=$("composer-grid");grid.replaceChildren();grid.style.setProperty("--rows",isDrums?5:12);
  const corner=document.createElement("span");corner.textContent=isDrums?"DRUM":"PITCH";grid.append(corner);
  for(let step=0;step<16;step++){const label=document.createElement("span");label.textContent=step%4===0?String(step/4+1):"·";grid.append(label);}
  const rows=isDrums?["hat","clap","snare","rim","kick"]:Array.from({length:12},(_,i)=>base+11-i);
  for(const row of rows){const label=document.createElement("button");label.type="button";label.className="composer-note-label";label.textContent=isDrums?row:pitchNames[(row+config.key)%12]+String(Math.floor((row+config.key)/12)-1);label.setAttribute("aria-label","Hear "+names[part]+" "+label.textContent);label.addEventListener("click",()=>hear(row,Number($("composer-length").value)));grid.append(label);
   for(let col=0;col<16;col++){const step=bar*16+col,button=document.createElement("button"),note=isDrums?null:(config.notes[part].find(n=>n.midi===row&&n.step===step)||config.notes[part].find(n=>n.midi===row&&n.step<step&&n.step+n.length>step)),active=isDrums?config.drums[row]?.includes(step):note?.step===step;
    button.type="button";button.className="composer-cell"+(active?" is-note":"")+(note&&!active?" is-held":"")+(col%4===0?" is-beat":"");button.setAttribute("aria-label",`${names[part]} ${label.textContent}, bar ${bar+1}, step ${col+1}${note?", length "+note.length:""}`);button.setAttribute("aria-pressed",String(Boolean(active||note)));button.textContent=active?"●":"";
    button.addEventListener("click",()=>{if(isDrums){const hits=config.drums[row]||[];config.drums[row]=hits.includes(step)?hits.filter(hit=>hit!==step):[...hits,step];}else{if(config.notes[part].length>=256&&!note){status("Maximum 256 notes per part. Remove a note first.");return;}config.notes[part]=toggleNote(config.notes[part],step,row,Number($("composer-length").value));}changed();hear(row,note?.length||Number($("composer-length").value));draw();});grid.append(button);
   }
  }
  const levels=$("composer-levels");levels.replaceChildren();for(const instrument of modes[config.mode]){const label=document.createElement("label");label.textContent=names[instrument];const range=document.createElement("input");range.type="range";range.min=0;range.max=1;range.step=.05;range.value=config.levels[instrument]??1;range.setAttribute("aria-label",names[instrument]+" volume");range.addEventListener("input",()=>{config.levels[instrument]=Number(range.value);changed();});label.append(range);levels.append(label);}
  $("composer-summary").textContent=`${config.bars} bars · ${config.bpm} BPM · ${pitchNames[config.key]} · four-bar pattern repeats ${config.bars/4} time(s). ${config.notes[part]?.length??Object.values(config.drums).reduce((sum,hits)=>sum+hits.length,0)} notes/hits in this part.`;
 }
 function hydrate(){
  $("composition-category").value=root.dataset.category;fillStyles();for(const name of ["mode","bpm","bars","key","progression"])$("composition-"+name).value=config[name];$("composer-octave").value=part==="bass"?36:part==="pad"?48:60;$("composer-length").value=part==="pad"?16:4;draw();
 }
 hydrate();
 for(const name of ["mode","bpm","bars","key","progression"]){$("composition-"+name).addEventListener("change",()=>{const input=$("composition-"+name),value=["bpm","bars","key"].includes(name)?Number(input.value):input.value;if(name==="bpm"&&(!Number.isInteger(value)||value<40||value>240)){input.value=config.bpm;status("Choose a tempo from 40 to 240 BPM.");return;}config[name]=value;changed();draw();});}
 $("composition-style").addEventListener("change",()=>{config.preset=$("composition-style").value;changed();});
 $("composition-category").addEventListener("change",()=>{fillStyles();$("composition-style").dispatchEvent(new Event("change",{bubbles:true}));changed();});
 $("composition-title").addEventListener("input",changed);
 for(const field of ["composer-bar","composer-octave"])$(field).addEventListener("change",draw);
 $("composer-generate").addEventListener("click",()=>{if(!confirm("Replace all four bars in every instrument with a new starting pattern?"))return;const pattern=StudioBeats.pattern(preset(),config.bpm,config);config.notes=pattern.notes;config.drums=pattern.drums;changed();draw();status("Starting pattern generated. Edit any cell to make it yours.");});
 $("composer-clear").addEventListener("click",()=>{const bar=Number($("composer-bar").value);if(!confirm("Clear this instrument in the selected bar?"))return;if(part==="drums")for(const instrument in config.drums)config.drums[instrument]=config.drums[instrument].filter(step=>Math.floor(step/16)!==bar);else config.notes[part]=config.notes[part].filter(note=>Math.floor(note.step/16)!==bar);changed();draw();});
 async function task(action){if(busy)return;auditioner.stop();busy=true;root.querySelectorAll("button,input,select").forEach(control=>control.disabled=true);try{await action();}catch(error){status(error.message||"Unable to complete this action. Your pattern is retained.");}finally{busy=false;root.querySelectorAll("button,input,select").forEach(control=>control.disabled=false);$("composer-use").disabled=dirty||!id;}}
 $("composer-play").addEventListener("click",()=>task(async()=>{status("Rendering four-bar preview…");$("composer-player").pause();const audio=await StudioBeats.render(preset(),config.bpm,4,config);if(url)URL.revokeObjectURL(url);url=URL.createObjectURL(wav(audio));$("composer-player").src=url;$("composer-player").hidden=false;await $("composer-player").play();status("Previewing your four-bar pattern.");}));
 $("composer-stop").addEventListener("click",()=>{auditioner.stop();$("composer-player").pause();$("composer-player").currentTime=0;status("Playback stopped.");});
 $("composer-save").addEventListener("click",()=>task(async()=>{
  const title=$("composition-title").value.trim();if(!title||title.length>160)throw new Error("Enter an instrumental name up to 160 characters.");
  $("composer-player").pause();status("Rendering and saving your instrumental…");const audio=await StudioBeats.render(preset(),config.bpm,config.bars,config),data=new FormData();data.append("title",title);data.append("category",$("composition-category").value);data.append("config",JSON.stringify(config));data.append("audio",wav(audio),"instrumental.wav");data.append("revision",revision);
  const response=await fetch(id?`/studio/instrumentals/${id}/save/`:"/studio/instrumentals/save/",{method:"POST",headers:{"X-CSRFToken":root.querySelector("[name=csrfmiddlewaretoken]").value},body:data}),result=await response.json();if(!response.ok)throw new Error(result.error||"Unable to save. Your pattern is retained.");
  try{localStorage.removeItem(draftKey());}catch(_){}id=String(result.id);revision=result.revision;dirty=false;history.replaceState(null,"",result.url);$("composer-use-form").action=`/studio/instrumentals/${id}/use/`;$("composer-state").textContent="Saved to Instrumental Library";$("composer-recovery").hidden=true;status("Instrumental saved. Use in Studio to start a vocal session, or reopen it from your library later.");
 }));
 $("composer-use-form").addEventListener("submit",event=>{if(dirty||!id||busy){event.preventDefault();status("Save your instrumental before using it in Studio.");}});
 if(id)$("composer-state").textContent="Saved instrumental";
 try{const saved=JSON.parse(localStorage.getItem(draftKey())||"null");if(saved&&saved.revision===revision){$("composer-recovery").hidden=false;$("composer-restore").addEventListener("click",()=>{try{StudioBeats.arrangement(presets.find(p=>p.id===saved.config.preset),saved.config.bpm,4,saved.config);config=saved.config;root.dataset.category=saved.category;$("composition-title").value=saved.title;defaults();hydrate();for(const input of root.querySelectorAll("select"))input.dispatchEvent(new Event("change",{bubbles:true}));changed();$("composer-recovery").hidden=true;status("Draft restored. Preview and save when ready.");}catch(_){status("This draft could not be restored. Your saved instrumental is unchanged.");}});$("composer-discard").addEventListener("click",()=>{localStorage.removeItem(draftKey());$("composer-recovery").hidden=true;});}}catch(_){}
 window.addEventListener("beforeunload",event=>{if(dirty){event.preventDefault();event.returnValue="";}});
 window.addEventListener("pagehide",()=>{auditioner.close();$("composer-player").pause();if(url)URL.revokeObjectURL(url);});
})(typeof window!=="undefined"?window:globalThis);
