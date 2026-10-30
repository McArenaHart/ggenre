/* Audio device choice. Listing is read-only; permission is requested only by a user action. */
(function(scope){
 "use strict";
 function constraints(deviceId="",keyboard=false){const audio={channelCount:keyboard?{ideal:2}:1,echoCancellation:false,noiseSuppression:false,autoGainControl:false};if(deviceId)audio.deviceId={exact:deviceId};return {audio};}
 function mount({media,select,scan,status,enabled=()=>true}){
  let disposed=false,busy=false,selected=select.value||"";
  async function refresh(){if(!media?.enumerateDevices)return;try{const devices=(await media.enumerateDevices()).filter(device=>device.kind==="audioinput");if(disposed)return;selected=select.value||selected;select.replaceChildren();const option=(value,label)=>{const item=document.createElement("option");item.value=value;item.textContent=label;select.append(item);};option("","System default input");devices.forEach((device,i)=>option(device.deviceId,device.label||"Audio input "+(i+1)));if(selected&&!devices.some(d=>d.deviceId===selected)){option(selected,"Selected input disconnected");status("The selected audio input is disconnected. Reconnect it or choose another input.");}select.value=selected;select.dispatchEvent(new Event("change",{bubbles:true}));}catch(error){status("Unable to list audio inputs: "+error.message);}}
  async function enable(){if(busy||!enabled()||!media?.getUserMedia)return;busy=true;scan.disabled=true;let stream;try{status("Allow audio access to show device names.");stream=await media.getUserMedia({audio:true});if(disposed)return;await refresh();status("Audio inputs ready. Select your microphone or keyboard/interface input.");}catch(error){if(!disposed)status(error.name==="NotAllowedError"?"Audio access was denied. You can retry when ready.":"Unable to enable audio inputs: "+error.message);}finally{stream?.getTracks().forEach(track=>track.stop());busy=false;if(!disposed)scan.disabled=false;}}
  const changed=()=>{selected=select.value;};select.addEventListener("change",changed);scan.addEventListener("click",enable);media?.addEventListener?.("devicechange",refresh);refresh();
  return {refresh,dispose(){disposed=true;media?.removeEventListener?.("devicechange",refresh);select.removeEventListener("change",changed);scan.removeEventListener("click",enable);}};
 }
 const api={constraints,mount};if(typeof module!=="undefined"&&module.exports)module.exports=api;else scope.StudioInputs=api;
})(typeof window!=="undefined"?window:globalThis);
