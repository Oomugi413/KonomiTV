import{d as I,q as u,C as b,z as q,x as w,c as r,F as R,w as n,a as l,k as V,h as P,r as m,b as h,D as W,n as D,B as E,o as t,R as d,_ as U}from"./index-DqbPFAT_.js";import{V as z,_ as F}from"./ssrBoot-B8cSVaW_.js";const H={key:1,class:"search-box"},K={class:"search-box__icon"},M=["placeholder"],N=I({__name:"SPHeaderBar",setup(T){const f=E(),a=q(),p=u(null),o=u(!1),s=u(""),y=b(()=>_(a.path)?"録画番組やシリーズを検索...":"放送予定の番組を検索..."),_=e=>e.startsWith("/videos")||e.startsWith("/mylist")||e.startsWith("/watched-history"),k=()=>_(a.path)?"/videos/search":"/tv/search",x=()=>{o.value=!0,setTimeout(()=>{var e;(e=p.value)==null||e.focus()},0)},v=()=>{o.value=!1,s.value=""},g=()=>{if(s.value.trim()){const e=k();f.push(`${e}?query=${encodeURIComponent(s.value.trim())}`)}},S=e=>{e.key==="Enter"?g():e.key==="Escape"&&v()};return w(()=>{a.path.endsWith("/search")&&a.query.query&&(s.value=decodeURIComponent(a.query.query),o.value=!0)}),(e,c)=>{const C=m("router-link"),i=m("Icon");return t(),r("header",{class:D(["header",{"search-active":o.value}])},[o.value?(t(),r("div",H,[h("div",K,[l(i,{icon:"fluent:search-20-filled",height:"20px"})]),n(h("input",{ref_key:"searchInput",ref:p,type:"search",enterkeyhint:"search",placeholder:y.value,"onUpdate:modelValue":c[0]||(c[0]=B=>s.value=B),onKeydown:S},null,40,M),[[W,s.value]]),n((t(),r("div",{class:"search-box__close",onClick:v},[l(i,{icon:"fluent:dismiss-20-filled",height:"24px"})])),[[d]])])):(t(),r(R,{key:0},[n((t(),V(C,{class:"konomitv-logo",to:"/tv/"},{default:P(()=>c[1]||(c[1]=[h("img",{class:"konomitv-logo__image",src:F,height:"21"},null,-1)])),_:1})),[[d]]),l(z),n((t(),r("div",{class:"search-button",onClick:x},[l(i,{icon:"fluent:search-20-filled",height:"24px"})])),[[d]])],64))],2)}}}),Q=U(N,[["__scopeId","data-v-7baf0778"]]);export{Q as S};
