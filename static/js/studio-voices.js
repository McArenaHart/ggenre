/* Acapella helpers. Guides and solo choices never become project audio tracks. */
(function(scope){
 "use strict";
 function nextName(part,tracks){
  const name=String(part||"Voice").trim().slice(0,96)||"Voice";
  const escaped=name.replace(/[.*+?^${}()|[\]\\]/g,"\\$&");
  const pattern=new RegExp("^"+escaped+"(?: (\\d+))?$","i");
  let maximum=0;
  for(const track of tracks){const match=String(track.name||"").trim().match(pattern);if(match)maximum=Math.max(maximum,Number(match[1])||1);}
  return maximum ? name.slice(0,95)+" "+(maximum+1) : name;
 }
 function monitoring(tracks,solo){return solo.size ? tracks.filter(track=>solo.has(track.id)) : tracks;}
 function frequency(midi){if(!Number.isInteger(midi)||midi<48||midi>72)throw new Error("Choose a reference note from C3 to C5.");return 440*Math.pow(2,(midi-69)/12);}
 function protect(buffer){
  let peak=0;for(let channel=0;channel<buffer.numberOfChannels;channel++)for(const value of buffer.getChannelData(channel)){if(!Number.isFinite(value))throw new Error("Invalid voice audio. Check your source tracks.");peak=Math.max(peak,Math.abs(value));}
  const gain=peak>.98?.98/peak:1;
  if(gain<1)for(let channel=0;channel<buffer.numberOfChannels;channel++){const samples=buffer.getChannelData(channel);for(let i=0;i<samples.length;i++)samples[i]*=gain;}
  return {peak,gain};
 }
 function reference(context,midi,onEnd=()=>{}){
  const oscillator=context.createOscillator(),gain=context.createGain(),now=context.currentTime;
  oscillator.type="sine";oscillator.frequency.setValueAtTime(frequency(midi),now);
  gain.gain.setValueAtTime(.0001,now);gain.gain.exponentialRampToValueAtTime(.1,now+.03);gain.gain.setValueAtTime(.1,now+.9);gain.gain.exponentialRampToValueAtTime(.0001,now+1.2);
  oscillator.connect(gain).connect(context.destination);let ended=false;
  function stop(){if(ended)return;ended=true;oscillator.onended=null;try{oscillator.stop();}catch(_){}oscillator.disconnect();gain.disconnect();onEnd();}
  oscillator.onended=stop;oscillator.start(now);oscillator.stop(now+1.21);return {stop};
 }
 const api={nextName,monitoring,frequency,protect,reference};
 if(typeof module!=="undefined"&&module.exports)module.exports=api;else scope.StudioVoices=api;
})(typeof window!=="undefined"?window:globalThis);
