'use strict';
const vm=require('node:vm'),assert=require('node:assert/strict');
// Parse the whole declaration. Formatting, nested braces and template literals
// must not truncate the executable function supplied to a synthetic DOM.
function extractFunction(source,name){
 const lines=source.split(/\r?\n/),pattern=new RegExp('^(?:async )?function '+name+'\\(');
 const starts=lines.flatMap((line,i)=>pattern.test(line)?[i]:[]);
 assert.equal(starts.length,1,`exactly one declaration required: ${name}`);
 for(let end=starts[0]+1;end<=lines.length;end++){
  const declaration=lines.slice(starts[0],end).join('\n');
  try{new vm.Script(declaration,{filename:name+'.extracted.js'});return declaration}catch{}
 }
 throw new SyntaxError('Incomplete function declaration: '+name);
}
module.exports={extractFunction};
