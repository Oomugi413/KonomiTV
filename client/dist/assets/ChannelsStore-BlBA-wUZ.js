import{a7 as _,cy as y,U as p,u as S}from"./index-CyocJmOS.js";class B{static getChannelType(t){var n,e;try{const s=(e=(n=t.match("(?<channel_type>[a-z]+(?:4k)?)\\d+"))==null?void 0:n.groups)==null?void 0:e.channel_type.toUpperCase();if(!s)return null;switch(s){case"GR":return"GR";case"BS":return"BS";case"CS":return"CS";case"CATV":return"CATV";case"SKY":return"SKY";case"BS4K":return"BS4K";default:return null}}catch{return null}}static getChannelForceType(t){return t===null?"normal":t>=500?"festival":t>=200?"so-many":t>=100?"many":"normal"}static getChannelHashtag(t){const n={NHK総合:"#nhk",NHKEテレ:"#etv",HBC:"#hbc",札幌テレビ:"#stv",HTB:"#htb",TVh:"#tvh",北海道文化放送:"#uhb",RAB青森放送:"#rab",青森朝日放送:"#aba",ATV青森テレビ:"#atv",テレビ岩手:"#tvi",岩手朝日テレビ:"#iat",IBCテレビ:"#ibc",めんこいテレビ:"#mit",TBCテレビ:"#tbc",ミヤギテレビ:"#mmt",東日本放送:"#khb",仙台放送:"#oxtv",ABS秋田放送:"#abs",秋田朝日放送:"#aab",AKT秋田テレビ:"#akt",山形放送:"#ybc",山形テレビ:"#yts",TUY:"#tuy",さくらんぼテレビ:"#say",福島中央テレビ:"#fct",KFB福島放送:"#kfb",テレビユー福島:"#tuf",FTV福島テレビ:"#ftv",TeNY:"#TeNY",新潟テレビ21:"#uxtv",BSN:"#bsn",NST:"#nst",KNBテレビ:"#knb",チューリップテレビ:"#tut",富山テレビ放送:"#toyamatv",テレビ金沢:"#tv_kanazawa",HAB:"#hab",MRO:"#mro",石川テレビ:"#ishikawatv",福井放送:"#fbc",福井テレビ:"#fukuitv",山梨放送:"#ybs",UTYテレビ山梨:"#uty",テレビ信州:"#tsb",長野朝日放送:"#abn",SBC信越放送:"#sbc",長野放送:"#nbs","Daiichi-TV":"#sdt",静岡朝日テレビ:"#satv",SBS:"#sbs",テレビ静岡:"#sut",三重テレビ:"#mietv",ぎふチャン:"#gifuchan",BBCびわ湖放送:"#BBC_biwako",奈良テレビ:"#tvn",WTV:"#telewaka",RNC西日本テレビ:"#rnc",瀬戸内海放送:"#ksb",RSKテレビ:"#rsk",TSCテレビせとうち:"#tvsetouchi",OHK:"#ohk",RCCテレビ:"#rcc",広島テレビ:"#htv",広島ホームテレビ:"#hometv",テレビ新広島:"#tss",日本海テレビ:"#nkt",BSSテレビ:"#bss",さんいん中央テレビ:"#tsk",tysテレビ山口:"#tys",山口放送:"#kry",yab山口朝日:"#yab",四国放送:"#jrt",高知放送:"#rkc",テレビ高知:"#kutv",高知さんさんテレビ:"#kss",南海放送:"#rnb",愛媛朝日テレビ:"#eat",あいテレビ:"#itv",テレビ愛媛:"#ebc",KBCテレビ:"#kbc",RKB毎日放送:"#rkb",FBS福岡放送:"#fbs",TVQ九州放送:"#tvq",テレビ西日本:"#tnc",STSサガテレビ:"#sagatv",NBC長崎放送:"#nbc",長崎国際テレビ:"#nib",NCC長崎文化放送:"#ncc",テレビ長崎:"#ktn",RKK熊本放送:"#rkk",くまもと県民:"#kkt",KAB熊本朝日放送:"#kab",テレビ熊本:"#tku",OBS大分放送:"#obs",TOSテレビ大分:"#tos",OAB大分朝日放送:"#oab",MRT宮崎放送:"#mrt",テレビ宮崎:"#umk",MBC南日本放送:"#mbc",鹿児島讀賣テレビ:"#kyt",KKB鹿児島放送:"#kkb",鹿児島テレビ放送:"#kts",RBCテレビ:"#rbc",琉球朝日放送:"#qab",沖縄テレビ:"#otv",日テレ:"#ntv",読売テレビ:"#ytv",中京テレビ:"#chukyotv",テレビ朝日:"#tvasahi",ABCテレビ:"#abc","メ~テレ":"#nagoyatv","メ〜テレ":"#nagoyatv",TBSチャンネル:null,TBS:"#tbs",MBS:"#mbs",CBC:"#cbc",テレビ東京:"#tvtokyo",テレ東:"#tvtokyo",テレビ大阪:"#tvo",テレビ愛知:"#tva",フジテレビ:"#fujitv",関西テレビ:"#kantele",東海テレビ:"#tokaitv","TOKYO MX":"#tokyomx",tvk:"#tvk",チバテレ:"#chibatv",テレ玉:"#teletama",群馬テレビ:"#gtv",とちぎテレビ:"#tochitere",とちテレ:"#tochitere",サンテレビ:"#suntv",KBS京都:"#kbs",NHKBS1:"#nhkbs1",NHKBSプレミアム:"#nhkbsp",NHKBS:"#nhkbs",BS日テレ:"#bsntv",BS朝日:"#bsasahi","BS-TBS":"#bstbs",BSテレ東:"#bstvtokyo",BSフジ:"#bsfuji",BS10スターチャンネル:"#bs10スターチャンネル",BS10:"#bs10",BS11:"#bs11",BS12:"#bs12",BS松竹東急:"#bs260ch",BSJapanext:"#bsjapanext",BSよしもと:"#bsyoshimoto","AT-X":"#at_x"},e=Object.keys(n).find(s=>t.startsWith(s));return e?n[e]:null}}const f={id:"NID0-SID0-EID0",channel_id:"NID0-SID0",network_id:0,service_id:0,event_id:0,title:"取得中…",description:"取得中…",detail:{},start_time:"2000-01-01T00:00:00+09:00",end_time:"2000-01-01T00:00:00+09:00",duration:0,is_free:!0,genres:[],video_type:"映像1080i(1125i)、アスペクト比16:9 パンベクトルなし",video_codec:"MPEG-2",video_resolution:"1080i",primary_audio_type:"2/0モード(ステレオ)",primary_audio_language:"日本語",primary_audio_sampling_rate:"48kHz",secondary_audio_type:null,secondary_audio_language:null,secondary_audio_sampling_rate:null},d={id:"NID0-SID0",display_channel_id:"gr000",network_id:0,service_id:0,transport_stream_id:null,remocon_id:0,channel_number:"---",type:"GR",name:"取得中…",jikkyo_force:null,is_subchannel:!1,is_radiochannel:!1,is_watchable:!0,is_display:!0,viewer_count:0,program_present:f,program_following:f};class v{static async fetchAllChannels(){const t=await _.get("/channels");return t.type==="error"?(_.showGenericError(t,"チャンネル情報を取得できませんでした。"),null):t.data}static async fetch(t){const n=await _.get(`/channels/${t}`);return n.type==="error"?(_.showGenericError(n,"チャンネル情報を取得できませんでした。"),null):n.data}static async fetchWebSocketInfo(t){const n=await _.get(`/channels/${t}/jikkyo`);return n.type==="error"?(_.showGenericError(n,"コメント送受信用 WebSocket API の情報を取得できませんでした。"),null):n.data}}const m=y("channels",{state:()=>({channels_list:{GR:[],BS:[],CS:[],CATV:[],SKY:[],BS4K:[]},is_channels_list_initial_updated:!1,last_updated_at:0,display_channel_id:"gr000",viewer_count:null,current_program_present:null,current_program_following:null}),getters:{channel(){if(this.is_channels_list_initial_updated===!1)return{previous:d,current:d,next:d};const a={...f,title:"チャンネル情報取得エラー",description:"このチャンネル ID のチャンネル情報は存在しません。"},t={...d,name:"チャンネル情報取得エラー",program_present:a,program_following:a},n=B.getChannelType(this.display_channel_id);if(n===null)return{previous:t,current:t,next:t};const e=this.channels_list[n],s=e.findIndex(i=>i.display_channel_id===this.display_channel_id);if(s===-1)return{previous:t,current:t,next:t};const l=(()=>{let i=s-1;for(;e.length;){if(i<=-1&&(i=e.length-1),e[i].is_display)return i;i--}return 0})(),o=(()=>{let i=s+1;for(;e.length;){if(i>=e.length&&(i=0),e[i].is_display)return i;i++}return 0})(),c=structuredClone(e[s]);return this.current_program_present!==null&&(c.program_present=this.current_program_present),this.current_program_following!==null&&(c.program_following=this.current_program_following),this.viewer_count!==null&&(c.viewer_count=this.viewer_count),{previous:e[l],current:c,next:e[o]}},channels_list_with_pinned(){var e,s,l,o,c,i,b;const a=S(),t=new Map;if(t.set("ピン留め",[]),t.set("地デジ",[]),this.is_channels_list_initial_updated===!1)return t;t.set("BS",[]),t.set("CS",[]),t.set("CATV",[]),t.set("SKY",[]),t.set("BS4K",[]);const n=[];for(const[h,u]of Object.entries(this.channels_list))for(const r of u)if(a.settings.pinned_channel_ids.includes(r.id)&&n.push(r),r.is_display!==!1)switch(r.type){case"GR":{(e=t.get("地デジ"))==null||e.push(r);break}case"BS":{(s=t.get("BS"))==null||s.push(r);break}case"CS":{(l=t.get("CS"))==null||l.push(r);break}case"CATV":{(o=t.get("CATV"))==null||o.push(r);break}case"SKY":{(c=t.get("SKY"))==null||c.push(r);break}case"BS4K":{(i=t.get("BS4K"))==null||i.push(r);break}}(b=t.get("ピン留め"))==null||b.push(...n.sort((h,u)=>{const r=a.settings.pinned_channel_ids.indexOf(h.id),g=a.settings.pinned_channel_ids.indexOf(u.id);return r-g}));for(const[h,u]of t)h!=="ピン留め"&&u.length===0&&t.delete(h);return t.size===1&&t.has("ピン留め")&&t.delete("ピン留め"),t},channels_list_with_pinned_for_watch(){var t;const a=new Map([...this.channels_list_with_pinned]);return this.is_channels_list_initial_updated===!1||((t=a.get("ピン留め"))==null?void 0:t.length)===0&&a.delete("ピン留め"),a}},actions:{getChannelByRemoconID(a,t){return this.channels_list[a].find(s=>s.remocon_id===t)??null},async update(a=!1){const t=async()=>{const e=await v.fetchAllChannels();e!==null&&(this.channels_list=p.deepObjectFreeze(e),this.is_channels_list_initial_updated===!1&&(this.is_channels_list_initial_updated=!0),this.last_updated_at=p.time())};if(this.is_channels_list_initial_updated===!0&&a===!1){p.time()-this.last_updated_at>60&&t();return}await t();const n=S();n.settings.pinned_channel_ids=n.settings.pinned_channel_ids.filter(e=>{var l;const s=(l=this.channels_list_with_pinned.get("ピン留め"))==null?void 0:l.some(o=>o.id===e);return s===!1&&console.warn("[ChannelsStore] Deleted pinned channel ID:",e),s})}}});export{B as C,d as I,v as a,f as b,m as u};
