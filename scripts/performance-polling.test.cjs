const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};}
function snippet(file,start,end){const source=fs.readFileSync(file,'utf8'),first=source.indexOf(start),last=source.indexOf(end,first);assert.ok(first>=0&&last>first);return source.slice(first,last);}
for(const [name,file,start,end,fn] of [
 ['admin badges','static/js/pages/base-shell.js','    let unreadPollRequest','\n    pollUnread();','pollUnread'],
 ['contact widget','static/js/pages/chatapp.js','    let contactStateRequest','\n    function setWidgetOpen','refreshAdminContactState']
]){
 test(name+' shares overlapping polls and retries after completion',async()=>{
  const requests=[],updates=[];
  const context={isAdminContactWidget:true,unreadUrl:'/counts/',inboxUrl:'/inbox/',lastCount:0,lastMissionRequestCount:0,fetch:()=>{const pending=deferred();requests.push(pending);return pending.promise;},syncAdminChatBadges:value=>updates.push(value),showAdminChatToast(){},updateAdminContactBadge:value=>updates.push(value),renderOtpNotice(){}};
  vm.createContext(context);vm.runInContext(snippet(file,start,end),context);
  const first=context[fn](),second=context[fn]();assert.equal(first,second);assert.equal(requests.length,1);
  requests[0].resolve({ok:true,json:async()=>({unread_count:3,mission_request_count:0,total_action_count:3})});await first;assert.deepEqual(updates,[3]);
  const retry=context[fn]();assert.equal(requests.length,2);requests[1].reject(new Error('offline'));await retry;
  const recovered=context[fn]();assert.equal(requests.length,3);requests[2].resolve({ok:false});await recovered;
 });
}
test('overlapping mission discovery shares network work without changing callers',async()=>{
 const requests=[],rendered=[],messages=[];
 const context={missionLatestUrl:'/missions/',statusEl:{},setText:(_,text)=>messages.push(text),renderMissionStatus:value=>rendered.push(value),getJson:()=>{const pending=deferred();requests.push(pending);return pending.promise;}};
 vm.createContext(context);vm.runInContext(snippet('static/js/pages/chatapp_missions.js','        let latestMissionRequest','\n        function initPullRefresh'),context);
 const automatic=context.refreshLatestMission({silent:true}),manual=context.refreshLatestMission();assert.equal(requests.length,1);assert.equal(messages.length,1);
 requests[0].resolve({mission:{id:7}});await Promise.all([automatic,manual]);assert.equal(rendered.length,2);assert.equal(rendered[0].id,7);
 const retry=context.refreshLatestMission();assert.equal(requests.length,2);requests[1].reject(new Error('offline'));await retry;
 const recovery=context.refreshLatestMission({silent:true});assert.equal(requests.length,3);requests[2].resolve({mission:null});await recovery;
});
