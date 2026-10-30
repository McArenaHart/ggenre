/* A shared audio clock drives the guide and vocal capture; video follows that clock. */
(function(scope){
  "use strict";
  function mixSettings(original, vocal, shift){
    const values=[original,vocal,shift].map(Number);
    if(!values.every(Number.isFinite)||values[0]<0||values[0]>2||values[1]<0||values[1]>2||values[2]<-1000||values[2]>1000)throw new Error("Check the song/voice volumes and alignment (−1000 to 1000 ms).");
    return {original_gain:values[0],vocal_gain:values[1],shift_ms:values[2]};
  }
  const countdown=remaining=>Math.min(4,Math.max(1,Math.ceil(remaining/.75)));
  if(typeof module!=="undefined"&&module.exports)module.exports={mixSettings,countdown};
  if(typeof document==="undefined")return;
  const root=document.getElementById("collaboration");if(!root)return;
  const $=id=>document.getElementById(id),video=$("collab-video");
  let phase="idle",token=0,session=null,stream=null,context=null,guide=null,take=null,takeURL=null,frame=0,started=false,renderKey=root.dataset.request,rendered=false;
  const status=text=>$("collab-status").textContent=text;
  function controls(){
    const active=["preparing","recording","stopping"].includes(phase),locked=active||phase==="rendering";
    $("collab-record").disabled=locked;$("collab-record").textContent=take?"Re-record my voice":"Record my voice";
    $("collab-stop").disabled=phase!=="recording";$("collab-cancel").hidden=!active;
    for(const id of ["collab-role","collab-original","collab-level","collab-shift","collab-render"])$(id).disabled=locked;
    $("collab-take").hidden=!take;$("collab-result").hidden=!rendered||locked;video.controls=!locked;
    root.dataset.state=phase;
  }
  function stopMedia(){cancelAnimationFrame(frame);video.pause();video.muted=false;if(stream)stream.getTracks().forEach(track=>track.stop());stream=null;}
  function fail(error){session?.cancel();session=null;stopMedia();phase=take?"review":"idle";controls();status(error.message||"Recording stopped. Please try again.");}
  function cancel(){$("collab-clock").textContent="Ready";token++;session?.cancel();session=null;stopMedia();phase=take?"review":"idle";controls();status("Take cancelled. Nothing was posted; your previous take is unchanged.");}
  async function loadGuide(){
    if(guide)return guide;
    const response=await fetch(root.dataset.audio);
    if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.error||"The source video is no longer available for collaboration.");}
    guide=await context.decodeAudioData(await response.arrayBuffer());
    if(!Number.isFinite(guide.duration)||guide.duration<=0||guide.duration>300.1)throw new Error("This video must be no longer than five minutes.");
    return guide;
  }
  function tick(){
    if(!session||phase!=="recording")return;
    const elapsed=context.currentTime-session.startTime;
    $("collab-clock").textContent=elapsed<0?"Ready · "+countdown(-elapsed):Math.max(0,elapsed).toFixed(1)+" s";
    if(elapsed>=0&&!started){started=true;video.currentTime=Math.min(elapsed,guide.duration);video.play().catch(error=>{if(phase==="recording")fail(new Error("Video playback was blocked. Play the original once, then try recording again."));});}
    if(started&&Math.abs(video.currentTime-elapsed)>.18&&elapsed<guide.duration)video.currentTime=Math.max(0,elapsed);
    if(elapsed>=guide.duration){phase="stopping";controls();video.pause();session.stop();return;}
    frame=requestAnimationFrame(tick);
  }
  $("collab-record").addEventListener("click",async()=>{
    const attempt=++token;phase="preparing";controls();status("Preparing the original song and microphone. Cancel is available while preparing.");
    try{
      if(!navigator.mediaDevices?.getUserMedia)throw new Error("Microphone recording requires HTTPS or localhost and a supported browser.");
      context=context||new (scope.AudioContext||scope.webkitAudioContext)();await context.resume();
      await loadGuide();if(attempt!==token)return;
      const input=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:false,noiseSuppression:true,autoGainControl:false},video:false});
      if(attempt!==token){input.getTracks().forEach(track=>track.stop());return;}
      stream=input;video.pause();video.currentTime=0;video.muted=true;$("collab-vocal").pause();$("collab-preview").pause();started=false;
      const correction=StudioAudio.estimatedDelay(context,input);
      const prepared=await StudioAudio.begin({context,stream:input,tracks:[{name:"Original song",trim_start:0,trim_end:guide.duration,offset:0,gain:1,muted:false}],load:async()=>guide,position:0,bpm:80,countIn:4,workletURL:"/static/js/studio-capture-worklet.js?v=4",onMeter:()=>{},onProgress:()=>{},onError:error=>{if(attempt===token)fail(error);},onDone:result=>{
        if(attempt!==token)return;
        session=null;stopMedia();
        try{
          if(result.samples.length/result.sampleRate<.1)throw new Error("The take was too short. Record a longer part.");
          const samples=StudioAudio.compensate(result.samples,result.sampleRate,correction).slice(0,Math.floor(guide.duration*result.sampleRate));
          take={samples,sampleRate:result.sampleRate};
          if(takeURL)URL.revokeObjectURL(takeURL);
          takeURL=URL.createObjectURL(StudioComposer.wav({numberOfChannels:1,length:samples.length,sampleRate:result.sampleRate,getChannelData:()=>samples}));
          $("collab-vocal").src=takeURL;$("collab-result").hidden=true;rendered=false;renderKey=crypto.randomUUID();phase="review";controls();status("Take ready. Listen to your voice, then create a combined video preview.");
        }catch(error){fail(error);}
      }});
      if(attempt!==token){prepared.cancel();return;}
      session=prepared;phase="recording";controls();status("Four-beat count-in. Sing with the original song through your headphones.");frame=requestAnimationFrame(tick);
    }catch(error){if(attempt===token)fail(error);}
  });
  $("collab-cancel").addEventListener("click",cancel);
  $("collab-stop").addEventListener("click",()=>{if(!session)return;phase="stopping";controls();video.pause();session.stop();});
  for(const id of ["collab-role","collab-original","collab-level","collab-shift"])$(id).addEventListener("change",()=>{if(!take)return;rendered=false;renderKey=crypto.randomUUID();$("collab-result").hidden=true;$("collab-preview").pause();status("Mix settings changed. Create a fresh video preview before posting.");});
  $("collab-render").addEventListener("click",async()=>{
    if(!take)return;
    try{
      const settings=mixSettings($("collab-original").value,$("collab-level").value,$("collab-shift").value);
      phase="rendering";controls();status("Creating your combined video… Keep this tab open. Your take is retained if processing fails.");
      const data=new FormData();data.append("audio",StudioComposer.wav({numberOfChannels:1,length:take.samples.length,sampleRate:take.sampleRate,getChannelData:()=>take.samples}),"voice.wav");
      data.append("request_id",renderKey);data.append("role",$("collab-role").value);for(const [key,value] of Object.entries(settings))data.append(key,value);
      const response=await fetch(root.dataset.save,{method:"POST",headers:{"X-CSRFToken":root.querySelector("[name=csrfmiddlewaretoken]").value},body:data});
      const result=await response.json().catch(()=>({error:"The video could not be created. Please try again."}));
      if(!response.ok){renderKey=crypto.randomUUID();throw new Error(result.error);}
      $("collab-preview").src=result.preview;$("collab-publish").action=result.publish;$("collab-result").hidden=false;rendered=true;phase="review";controls();status("Preview saved privately. Watch it before submitting your collaboration to GGenre.");
    }catch(error){phase="review";controls();status(error.message);}
  });
  $("collab-publish").addEventListener("submit",()=>{rendered=true;});
  document.addEventListener("visibilitychange",()=>{if(document.hidden&&["preparing","recording","stopping"].includes(phase))cancel();});
  scope.addEventListener("beforeunload",event=>{if(["preparing","recording","stopping","rendering"].includes(phase)||(take&&!rendered)){event.preventDefault();event.returnValue="";}});
  scope.addEventListener("pagehide",()=>{token++;session?.cancel();stopMedia();context?.close();if(takeURL)URL.revokeObjectURL(takeURL);});
  controls();
})(typeof window!=="undefined"?window:globalThis);
