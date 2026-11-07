'use strict';
// Use Node's structured coverage event, never rounded console percentages.
module.exports=async function*(events){
 for await(const event of events){
  if(event.type==='test:coverage')yield JSON.stringify({coverage:event.data.summary})+'\n';
  if(event.type==='test:fail')yield JSON.stringify({failure:{name:event.data.name,message:String(event.data.details?.error||'unit test failed')}})+'\n';
 }
};
