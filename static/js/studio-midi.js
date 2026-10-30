/* MIDI input only. No SysEx or MIDI output; no permission request until Connect. */
(function(scope){
 "use strict";
 function create({requestAccess,onNoteOn=()=>{},onNoteOff=()=>{},onChange=()=>{},onStatus=()=>{}}){
  let access=null,selected="",channel=-1,epoch=0;const handlers=new Map(),notes=new Map(),pedals=new Set();
  const key=(port,ch,pitch)=>JSON.stringify([port,ch,pitch]);
  function release(id){const note=notes.get(id);if(!note)return;notes.delete(id);onNoteOff({...note,id});}
  function panic(port=null,ch=null){for(const [id,note] of [...notes])if((port===null||note.port===port)&&(ch===null||note.channel===ch))release(id);for(const pedal of [...pedals]){const [p,c]=JSON.parse(pedal);if((port===null||p===port)&&(ch===null||c===ch))pedals.delete(pedal);}}
  function receive(port,data){
   if(!data||data.length<2||selected&&selected!==port)return;const command=data[0]&240,ch=data[0]&15,pitch=data[1],value=data[2]??0;if(channel!==-1&&channel!==ch)return;if(!Number.isInteger(pitch)||pitch<0||pitch>127||!Number.isInteger(value)||value<0||value>127)return;
   const id=key(port,ch,pitch),pedal=JSON.stringify([port,ch]);
   if(command===144&&value>0){release(id);const note={port,channel:ch,pitch,velocity:value/127,down:true};notes.set(id,note);onNoteOn({...note,id});}
   else if(command===128||command===144&&value===0){const note=notes.get(id);if(!note)return;note.down=false;if(!pedals.has(pedal))release(id);}
   else if(command===176&&pitch===64){if(value>=64)pedals.add(pedal);else{pedals.delete(pedal);for(const [held,note] of [...notes])if(note.port===port&&note.channel===ch&&!note.down)release(held);}}
   else if(command===176&&(pitch===120||pitch===123))panic(port,ch);
  }
  function sync(){
   const inputs=[...(access?.inputs?.values()||[])].filter(input=>input.state!=="disconnected"),ids=new Set(inputs.map(input=>input.id));
   for(const [id,entry] of [...handlers])if(!ids.has(id)){entry.input.removeEventListener("midimessage",entry.handler);handlers.delete(id);panic(id);onStatus("MIDI input disconnected. Held notes were released.");}
   for(const input of inputs)if(!handlers.has(input.id)){const handler=event=>receive(input.id,event.data);input.addEventListener("midimessage",handler);handlers.set(input.id,{input,handler});try{input.open?.()?.catch?.(error=>onStatus("Unable to open MIDI input: "+error.message));}catch(error){onStatus("Unable to open MIDI input: "+error.message);}}
   onChange({connected:!!access,selected,channel,inputs:inputs.map(input=>({id:input.id,name:input.name||"MIDI input",manufacturer:input.manufacturer||""}))});
  }
  async function connect(){if(access){sync();return;}const token=++epoch;onStatus("Waiting for MIDI access…");const granted=await requestAccess({sysex:false});if(token!==epoch)return;access=granted;access.addEventListener("statechange",sync);sync();onStatus(access.inputs.size?"MIDI ready. Choose an input and play the active instrument.":"MIDI connected. Plug in a keyboard to begin.");}
  function choose(id){panic();selected=String(id||"");sync();}
  function chooseChannel(value){if(!Number.isInteger(value)||value< -1||value>15)throw new Error("Choose a MIDI channel from 1 to 16, or All.");panic();channel=value;sync();}
  function close(){epoch++;panic();for(const {input,handler} of handlers.values()){input.removeEventListener("midimessage",handler);try{input.close?.()?.catch?.(()=>{});}catch(_){}}handlers.clear();access?.removeEventListener("statechange",sync);access=null;sync();onStatus("MIDI disconnected.");}
  return {connect,choose,chooseChannel,panic,close,receive};
 }
 const api={create};if(typeof module!=="undefined"&&module.exports)module.exports=api;else scope.StudioMIDI=api;
})(typeof window!=="undefined"?window:globalThis);
