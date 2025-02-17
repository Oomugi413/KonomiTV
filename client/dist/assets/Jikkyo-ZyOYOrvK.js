import{a8 as c,d as w,m as k,M as n,U as F,a4 as S,u as y,_ as V,k as U,h as C,b as t,a as o,w as N,c as m,r as d,e as A,l as s,V as _,t as p,n as $,o as B,R as T}from"./index-CYWMZUuQ.js";import{C as P}from"./CommentMuteSettings-Cyk3I7c-.js";import{S as R}from"./Base-Cqvjydi3.js";import{V as f}from"./VSwitch-DlVOjzbP.js";import{V as D}from"./VSlider-BdGTSo9L.js";import"./VCard-DDKqZHSy.js";import"./ssrBoot-KQceIYXz.js";import"./VAvatar-O5Mngihm.js";import"./VTextField-BtpigOdW.js";import"./VSelect-BuOQm5N4.js";import"./VChip-DPUqQDlw.js";import"./VDialog-mKBQo0b-.js";import"./Navigation-_lN4rKee.js";class h{static async fetchAuthorizationURL(){const u=await c.get("/niconico/auth");return u.type==="error"?(c.showGenericError(u,"ニコニコアカウントとの連携用の認証 URL を取得できませんでした。"),null):u.data.authorization_url}static async logoutAccount(){const u=await c.delete("/niconico/logout");return u.type==="error"?(c.showGenericError(u,"ニコニコアカウントとの連携を解除できませんでした。"),!1):!0}}const I=w({name:"Settings-Jikkyo",components:{SettingsBase:R,CommentMuteSettings:P},data(){return{comment_mute_settings_modal:!1,is_loading:!0}},computed:{...k(y,S)},async created(){if(await this.userStore.fetchUser(),this.is_loading=!1,location.hash!==""){const e=new URLSearchParams(location.hash.replace("#",""));if(e.get("status")!==null&&e.get("detail")!==null){const u=parseInt(e.get("status")),l=e.get("detail");this.onOAuthCallbackReceived(u,l),history.replaceState(null,""," ")}}},methods:{async loginNiconicoAccount(){if(this.userStore.is_logged_in===!1){n.warning("連携をはじめるには、KonomiTV アカウントにログインしてください。");return}const e=await h.fetchAuthorizationURL();if(e===null)return;if(F.isMobileDevice()===!0){location.href=e;return}const u=window.open(e,"KonomiTV-OAuthPopup",F.getWindowFeatures());if(u===null){n.error("ポップアップウインドウを開けませんでした。");return}const l=async a=>{if(u.closed||F.typeof(a.data)!=="object"||!("KonomiTV-OAuthPopup"in a.data))return;u&&u.close(),window.removeEventListener("message",l);const E=a.data["KonomiTV-OAuthPopup"].status,g=a.data["KonomiTV-OAuthPopup"].detail;this.onOAuthCallbackReceived(E,g)};window.addEventListener("message",l)},async onOAuthCallbackReceived(e,u){if(console.log(`NiconicoAuthCallbackAPI: Status: ${e} / Detail: ${u}`),e!==200){if(u.startsWith("Authorization was denied (access_denied)"))n.error("ニコニコアカウントとの連携がキャンセルされました。");else if(u.startsWith("Failed to get access token (HTTP Error ")){const l=u.replace("Failed to get access token ","");n.error(`アクセストークンの取得に失敗しました。${l}`)}else if(u.startsWith("Failed to get access token (Connection Timeout)"))n.error("アクセストークンの取得に失敗しました。ニコニコで障害が発生している可能性があります。");else if(u.startsWith("Failed to get user information (HTTP Error ")){const l=u.replace("Failed to get user information ","");n.error(`ニコニコアカウントのユーザー情報の取得に失敗しました。${l}`)}else u.startsWith("Failed to get user information (Connection Timeout)")?n.error("ニコニコアカウントのユーザー情報の取得に失敗しました。ニコニコで障害が発生している可能性があります。"):n.error(`ニコニコアカウントとの連携に失敗しました。(${u})`);return}await this.userStore.fetchUser(!0),n.success("ニコニコアカウントと連携しました。")},async logoutNiconicoAccount(){await h.logoutAccount()!==!1&&(await this.userStore.fetchUser(!0),n.success("ニコニコアカウントとの連携を解除しました。"))}}}),M={class:"settings__heading"},O={key:0,class:"niconico-account niconico-account--anonymous"},W={class:"niconico-account-wrapper"},j={key:1,class:"niconico-account"},J={class:"niconico-account-wrapper"},L=["src"],K={class:"niconico-account__info"},X={class:"niconico-account__info-name"},z={class:"niconico-account__info-name-text"},G={class:"niconico-account__info-description"},H=["href"],q={key:0,class:"text-secondary"},Q={class:"settings__item settings__item--switch"},Y={class:"settings__item"},Z={class:"settings__item"},x={class:"settings__item settings__item--switch"};function uu(e,u,l,a,E,g){const r=d("Icon"),b=d("CommentMuteSettings"),v=d("SettingsBase");return B(),U(v,null,{default:C(()=>[t("h2",M,[N((B(),m("a",{class:"settings__back-button",onClick:u[0]||(u[0]=i=>e.$router.back())},[o(r,{icon:"fluent:chevron-left-12-filled",width:"27px"})])),[[T]]),o(r,{icon:"bi:chat-left-text-fill",width:"19px"}),u[9]||(u[9]=t("span",{class:"ml-3"},"ニコニコ実況",-1))]),t("div",{class:$(["settings__content",{"settings__content--loading":e.is_loading}])},[e.userStore.user===null||e.userStore.user.niconico_user_id===null?(B(),m("div",O,[t("div",W,[o(r,{class:"flex-shrink-0",icon:"bi:chat-left-text-fill",width:"45px"}),u[10]||(u[10]=t("div",{class:"niconico-account__info ml-4"},[t("div",{class:"niconico-account__info-name"},[t("span",{class:"niconico-account__info-name-text"},"ニコニコアカウントと連携していません")]),t("span",{class:"niconico-account__info-description"}," ニコニコアカウントと連携すると、テレビを見ながらニコニコ実況にコメントできるようになります。 ")],-1))]),o(_,{class:"niconico-account__login ml-auto",color:"secondary",width:"130",height:"56",variant:"flat",onClick:u[1]||(u[1]=i=>e.loginNiconicoAccount())},{default:C(()=>[o(r,{icon:"fluent:plug-connected-20-filled",class:"mr-2",height:"26"}),u[11]||(u[11]=s("連携する "))]),_:1})])):A("",!0),e.userStore.user!==null&&e.userStore.user.niconico_user_id!==null?(B(),m("div",j,[t("div",J,[t("img",{class:"niconico-account__icon",src:e.userStore.user_niconico_icon_url??""},null,8,L),t("div",K,[t("div",X,[t("span",z,p(e.userStore.user.niconico_user_name)+" と連携しています",1)]),t("span",G,[u[12]||(u[12]=t("span",{class:"mr-2",style:{"white-space":"nowrap"}},"Niconico User ID:",-1)),t("a",{class:"link mr-2",href:`https://www.nicovideo.jp/user/${e.userStore.user.niconico_user_id}`,target:"_blank"},p(e.userStore.user.niconico_user_id),9,H),e.userStore.user.niconico_user_premium===!0?(B(),m("span",q,"(Premium)")):A("",!0)])])]),o(_,{class:"niconico-account__login ml-auto",color:"secondary",width:"130",height:"56",variant:"flat",onClick:u[2]||(u[2]=i=>e.logoutNiconicoAccount())},{default:C(()=>[o(r,{icon:"fluent:plug-disconnected-20-filled",class:"mr-2",height:"26"}),u[13]||(u[13]=s("連携解除 "))]),_:1})])):A("",!0),t("div",Q,[u[14]||(u[14]=t("label",{class:"settings__item-heading",for:"prefer_posting_to_nicolive"},"可能であればニコニコ実況にコメントする",-1)),u[15]||(u[15]=t("label",{class:"settings__item-label",for:"prefer_posting_to_nicolive"},[t("ul",{class:"ml-4 mb-2 font-weight-bold"},[t("li",null,[s("オン："),t("a",{class:"link",href:"https://jk.nicovideo.jp",target:"_blank"},"ニコニコ実況"),s(" に優先的にコメントを送信")]),t("li",null,[s("オフ："),t("a",{class:"link",href:"https://nx-jikkyo.tsukumijima.net",target:"_blank"},"NX-Jikkyo"),s(" にコメントを送信")])]),s(" ニコニコ実況が利用できない場合（BS 民放など公式では廃止された実況チャンネル・ニコニコ生放送のメンテナンス中など）は、常に NX-Jikkyo にコメントします。 ")],-1)),u[16]||(u[16]=t("label",{class:"settings__item-label mt-2",for:"prefer_posting_to_nicolive"},[s(" ニコニコ実況にコメントするには、ニコニコアカウントとの連携が必要です。"),t("br"),s(" NX-Jikkyo は「ニコニコ実況の Web 版非公式コメントビューア」＋「ニコニコ実況公式にない実況チャンネルを補完する互換コメントサーバー」で、アカウント不要でコメントできます。"),t("br")],-1)),u[17]||(u[17]=t("label",{class:"settings__item-label mt-2",for:"prefer_posting_to_nicolive"}," ニコニコアカウント未連携でのコメント送信時に「代わりに NX-Jikkyo にコメントします」という通知を表示しないようにするには、この設定をオフにしてください。 ",-1)),o(f,{class:"settings__item-switch",color:"primary",id:"prefer_posting_to_nicolive","hide-details":"",modelValue:e.settingsStore.settings.prefer_posting_to_nicolive,"onUpdate:modelValue":u[3]||(u[3]=i=>e.settingsStore.settings.prefer_posting_to_nicolive=i)},null,8,["modelValue"])]),u[25]||(u[25]=t("div",{class:"settings__item"},[t("div",{class:"settings__item-heading"},"コメントのミュート設定"),t("div",{class:"settings__item-label"},[s(" 表示したくないコメントを、映像上やコメントリストに表示しないようにミュートできます。"),t("br")]),t("div",{class:"settings__item-label mt-2"},[s(" デフォルトでは、下記のミュート設定がオンになっています。"),t("br"),s(" これらのコメントも表示したい方は、適宜オフに設定してください。"),t("br"),t("ul",{class:"ml-5 mt-2"},[t("li",null,"露骨な表現を含むコメントをミュートする"),t("li",null,"ネガティブな表現、差別的な表現、政治的に偏った表現を含むコメントをミュートする"),t("li",null,"文字サイズが大きいコメントをミュートする")])])],-1)),o(_,{class:"settings__save-button mt-4",variant:"flat",onClick:u[4]||(u[4]=i=>e.comment_mute_settings_modal=!e.comment_mute_settings_modal)},{default:C(()=>[o(r,{icon:"heroicons-solid:filter",height:"19px"}),u[18]||(u[18]=t("span",{class:"ml-1"},"コメントのミュート設定を開く",-1))]),_:1}),u[26]||(u[26]=t("div",{class:"settings__quote mt-7"},[s(" コメントの透明度は、プレイヤー下にある設定アイコン ⚙️ から変更できます。"),t("br")],-1)),t("div",Y,[u[19]||(u[19]=t("div",{class:"settings__item-heading"},"コメントの速さ",-1)),u[20]||(u[20]=t("div",{class:"settings__item-label"},[s(" プレイヤーに流れるコメントの速さを設定します。"),t("br"),s(" たとえば 1.2 に設定すると、コメントが 1.2 倍速く流れます。"),t("br")],-1)),o(D,{class:"settings__item-form",color:"primary","show-ticks":"always","thumb-label":"","hide-details":"",step:.1,min:.5,max:2,modelValue:e.settingsStore.settings.comment_speed_rate,"onUpdate:modelValue":u[5]||(u[5]=i=>e.settingsStore.settings.comment_speed_rate=i)},null,8,["modelValue"])]),t("div",Z,[u[21]||(u[21]=t("div",{class:"settings__item-heading"},"コメントの文字サイズ",-1)),u[22]||(u[22]=t("div",{class:"settings__item-label"},[s(" プレイヤーに流れるコメントの文字サイズの基準値を設定します。"),t("br"),s(" 実際の文字サイズは画面サイズに合わせて調整されます。デフォルトの文字サイズは 34px です。"),t("br")],-1)),o(D,{class:"settings__item-form",color:"primary","show-ticks":"always","thumb-label":"","hide-details":"",step:1,min:20,max:60,modelValue:e.settingsStore.settings.comment_font_size,"onUpdate:modelValue":u[6]||(u[6]=i=>e.settingsStore.settings.comment_font_size=i)},null,8,["modelValue"])]),t("div",x,[u[23]||(u[23]=t("label",{class:"settings__item-heading",for:"close_comment_form_after_sending"},"コメント送信後にコメント入力フォームを閉じる",-1)),u[24]||(u[24]=t("label",{class:"settings__item-label",for:"close_comment_form_after_sending"},[s(" この設定をオンにすると、コメントを送信した後に、コメント入力フォームが自動で閉じるようになります。"),t("br"),s(" コメント入力フォームが表示されたままだと、大半のショートカットキーが文字入力と競合して使えなくなります。とくに理由がなければ、オンにしておくのがおすすめです。"),t("br")],-1)),o(f,{class:"settings__item-switch",color:"primary",id:"close_comment_form_after_sending","hide-details":"",modelValue:e.settingsStore.settings.close_comment_form_after_sending,"onUpdate:modelValue":u[7]||(u[7]=i=>e.settingsStore.settings.close_comment_form_after_sending=i)},null,8,["modelValue"])])],2),o(b,{modelValue:e.comment_mute_settings_modal,"onUpdate:modelValue":u[8]||(u[8]=i=>e.comment_mute_settings_modal=i)},null,8,["modelValue"])]),_:1})}const Fu=V(I,[["render",uu],["__scopeId","data-v-59490056"]]);export{Fu as default};
