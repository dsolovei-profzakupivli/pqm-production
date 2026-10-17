/* Consolidated 17 Oct contract supersedes compact-width assertions from 16 Oct.
   Both probes retain multiselect, copy, clears, themes, counts and no-F5 coverage. */
const {spawnSync}=require('node:child_process');
for(const probe of ['validation/ui_final_browser.cjs','validation/ui_improvements_browser.cjs']){
 const result=spawnSync(process.execPath,[probe],{cwd:require('node:path').resolve(__dirname,'..'),env:process.env,stdio:'inherit'});
 if(result.status!==0)process.exit(result.status||1);
}
