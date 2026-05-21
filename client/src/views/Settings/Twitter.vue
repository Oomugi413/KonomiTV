<template>
    <!-- ベース画面の中にそれぞれの設定画面で異なる部分を記述する -->
    <SettingsBase>
        <h2 class="settings__heading">
            <a v-ripple class="settings__back-button" @click="$router.back()">
                <Icon icon="fluent:chevron-left-12-filled" width="27px" />
            </a>
            <Icon icon="fa-brands:twitter" width="22px" />
            <span class="ml-3">Twitter</span>
        </h2>
        <div class="settings__content" :class="{'settings__content--loading': is_loading}">
            <div class="twitter-accounts">
                <div class="twitter-accounts__heading" v-if="userStore.user !== null && userStore.user.twitter_accounts.length > 0">
                    <Icon icon="fluent:person-board-20-filled" class="mr-2" height="30" />連携中のアカウント
                </div>
                <div class="twitter-accounts__guide" v-if="userStore.user === null || userStore.user.twitter_accounts.length === 0">
                    <Icon class="flex-shrink-0" icon="fa-brands:twitter" width="45px" />
                    <div class="ml-4">
                        <div class="font-weight-bold text-h6">Twitter アカウントと連携していません</div>
                        <div class="text-text-darken-1 text-subtitle-2 mt-1">
                            Twitter アカウントと連携すると、テレビを見ながら Twitter にツイートしたり、ほかの実況ツイートをリアルタイムで表示できるようになります。
                        </div>
                    </div>
                </div>
                <div class="twitter-account"
                    v-for="twitter_account in (userStore.user !== null ? userStore.user.twitter_accounts: [])"
                    :key="twitter_account.id">
                    <img class="twitter-account__icon" :src="twitter_account.icon_url">
                    <div class="twitter-account__info">
                        <div class="twitter-account__info-name">
                            <span class="twitter-account__info-name-text">{{twitter_account.name}}</span>
                        </div>
                        <span class="twitter-account__info-screen-name">
                            @{{twitter_account.screen_name}}
                        </span>
                    </div>
                    <v-btn class="twitter-account__logout ml-auto" width="124" height="52" variant="flat"
                        @click="logoutTwitterAccount(twitter_account.screen_name)">
                        <Icon icon="fluent:plug-disconnected-20-filled" class="mr-2" height="24" />連携解除
                    </v-btn>
                </div>
                <v-btn class="twitter-account__login" color="secondary" max-width="300" height="50" variant="flat"
                    @click="loginTwitterAccountWithCookieForm()">
                    <Icon icon="fluent:plug-connected-20-filled" class="mr-2" height="24" />連携する Twitter アカウントを追加
                </v-btn>
                <v-dialog max-width="740" v-model="twitter_cookie_auth_dialog">
                    <v-card>
                        <v-card-title class="d-flex justify-center pt-6 font-weight-bold">連携する Twitter アカウントを追加</v-card-title>
                        <v-card-text class="pt-2 pb-0">
                            <p>
                                2023年7月以降、<a class="link" href="https://www.watch.impress.co.jp/docs/news/1475575.html" target="_blank">Twitter のサードパーティー API の有料化（個人向け API の事実上廃止）</a> により、従来の連携方法では KonomiTV から Twitter にアクセスできなくなりました。
                            </p>
                            <p class="mt-1">
                                そこで KonomiTV では、<strong><a class="link" href="https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc" target="_blank">Chrome 拡張機能「GET cookies.txt LOCALLY」</a> を使い、ブラウザから Netscape 形式でエクスポートした、<a class="link" href="https://x.com/" target="_blank">Web 版 Twitter</a> の Cookie データによる Twitter 連携に対応しています。</strong>
                            </p>
                            <p class="mt-2">
                                <strong>ここで入力した Cookie データは、ローカルの KonomiTV サーバーにのみ、暗号化の上で保存されます。</strong><br>
                                Cookie データが Twitter API 以外の外部サービスに送信されることは一切ありません。
                            </p>
                            <p class="mt-1">
                                <strong>詳しい手順はこちら：<a class="link" href="https://github.com/Oomugi413/KonomiTV#twitter-実況機能について" target="_blank">KonomiTV への Twitter アカウント連携の手順</a></strong>
                            </p>
                            <blockquote class="mt-3">
                                ⚠️ 不審判定されないよう様々な技術的対策を施してはいますが、<strong>非公式な方法で無理やり実装しているため、今後の Twitter の仕様変更や不審判定基準の変更により、アカウントがロック・凍結される可能性も否定できません。</strong>自己の責任のもとでご利用ください。<br>
                                <p class="mt-2">
                                    <strong>📢 念のため、なるべく <a class="link" href="https://x.com/i/premium_sign_up" target="_blank">X Premium</a> に加入している Twitter アカウントでの利用をおすすめします。</strong><br>
                                    Basic プランでは <a class="link" href="https://pro.x.com/" target="_blank">X Pro (新 TweetDeck)</a> が使えないため、凍結避け効果は薄いと思われます。<br>
                                    また、万が一の凍結リスクに備え、<strong>実況専用に作成したサブアカウントでの連携をおすすめします。</strong>
                                </p>
                            </blockquote>
                            <blockquote class="mt-3">
                                📢 v0.13.0 以降では、<strong><a class="link" href="https://github.com/Oomugi413/KonomiTV/blob/master/server/app/utils/TwitterScrapeBrowser.py" target="_blank">ヘッドレスブラウザ（ウインドウが表示されないブラウザ）を使って</a> 、<a class="link" href="https://github.com/Oomugi413/KonomiTV/blob/master/server/static/zendriver_setup.js" target="_blank">Web 版 Twitter からの API コールと全く同じ方法で API リクエストを送る</a> ように改良しました！</strong><br>
                                <p class="mt-1">
                                    これまで不審判定されないよう <a class="link" href="https://github.com/tsukumijima/tweepy-authlib" target="_blank">様々な技術的対策</a> を施してきましたが、2025年11月に KonomiTV と同様の方法で Twitter API にアクセスしていた <a class="link" href="https://arkxv.com/blog/x-suspended/" target="_blank">OldTweetDeck のユーザーが一時的に大量凍結される騒動</a> (<a class="link" href="https://github.com/dimdenGD/OldTweetDeck/issues/459#issuecomment-3499066798" target="_blank">詳細</a>) が起きたことを踏まえ、より堅牢で安全なアプローチに切り替えました。<br>
                                </p>
                                <p class="mt-2">
                                    <strong>この関係で、Twitter 実況機能を使うには、KonomiTV サーバー側に <a class="link" href="https://www.google.com/chrome/" target="_blank">Google Chrome</a> または <a class="link" href="https://brave.com/ja/" target="_blank">Brave</a> がインストールされている必要があります。</strong>なお、Linux (Docker) 環境では既に Docker イメージに含まれているため不要です。また、Twitter 実況機能を使わないならインストールする必要はありません。
                                </p>
                                <p class="mt-2">
                                    ヘッドレスブラウザは、視聴画面で Twitter パネル内の各機能を使うときにバックグラウンドで自動的に起動し、使わなくなったら自動終了します。Twitter 実況機能が使われない場合には起動しません。
                                </p>
                            </blockquote>
                            <v-form class="settings__item" ref="twitter_form" @submit.prevent>
                                <v-textarea class="settings__item-form mt-4" style="height: 200px !important;" color="primary" variant="outlined"
                                    label='Cookie (Netscape cookies.txt 形式)'
                                    placeholder='まず Chrome 拡張機能「Get cookies.txt LOCALLY」を PC 版 Chrome にインストールします。次に Chrome の「シークレットウインドウ」で Web 版 Twitter を開き、連携したいアカウントにのみログインします。ログインできたら、Web 版 Twitter を開いているタブで Chrome 拡張機能「Get cookies.txt LOCALLY」を起動します。その後、[Export Format:] が [Netscape] になっていることを確認してから [Copy] ボタンを押し、クリップボードにコピーされた x.com の Cookie データをこのフォームに貼り付けてください。'
                                    v-model="twitter_cookie"
                                    :density="is_form_dense ? 'compact' : 'default'"
                                    :rules="[(value) => {
                                        if (!value) return 'Cookie を入力してください。';
                                        return true;
                                    }]">
                                </v-textarea>
                            </v-form>
                        </v-card-text>
                        <v-card-actions class="pt-0 px-6 pb-6">
                            <v-spacer></v-spacer>
                            <v-btn color="text" variant="text" height="40" @click="twitter_cookie_auth_dialog = false">キャンセル</v-btn>
                            <v-btn color="secondary" variant="flat" height="40" class="px-4" @click="loginTwitterAccountWithCookie()">ログイン</v-btn>
                        </v-card-actions>
                    </v-card>
                </v-dialog>
            </div>
            <div class="settings__item settings__item--switch">
                <label class="settings__item-heading" for="fold_panel_after_sending_tweet">ツイート送信後にパネルを自動で折りたたむ</label>
                <label class="settings__item-label" for="fold_panel_after_sending_tweet">
                    ツイートするとき以外はできるだけ映像を大きくして観たい方におすすめです。<br>
                </label>
                <v-switch class="settings__item-switch" color="primary" id="fold_panel_after_sending_tweet" hide-details
                    v-model="settingsStore.settings.fold_panel_after_sending_tweet">
                </v-switch>
            </div>
            <div class="settings__item settings__item--switch">
                <label class="settings__item-heading" for="reset_hashtag_when_program_switches">番組が切り替わったときにハッシュタグフォームをリセットする</label>
                <label class="settings__item-label" for="reset_hashtag_when_program_switches">
                    チャンネルを切り替えたときや、視聴中の番組が終了し次の番組の放送が開始されたときに、ハッシュタグフォームをリセットするかを設定します。<br>
                    オンにしておけば、「誤って前番組のハッシュタグをつけたまま、次の番組の実況ツイートをしてしまう」といったミスを防止できます。<br>
                </label>
                <v-switch class="settings__item-switch" color="primary" id="reset_hashtag_when_program_switches" hide-details
                    v-model="settingsStore.settings.reset_hashtag_when_program_switches">
                </v-switch>
            </div>
            <div class="settings__item settings__item--switch">
                <label class="settings__item-heading" for="auto_add_watching_channel_hashtag">視聴中のチャンネルに対応する局タグを自動で追加する</label>
                <label class="settings__item-label" for="auto_add_watching_channel_hashtag">
                    オンにすると、視聴中のチャンネルに対応する局タグ (#nhk, #tokyomx など) がハッシュタグフォームに自動で追加されます。<br>
                    なお、録画番組を視聴するときは、リアルタイム放送と誤解されないように、この設定がオンでも局タグは自動追加されません。<br>
                </label>
                <v-switch class="settings__item-switch" color="primary" id="auto_add_watching_channel_hashtag" hide-details
                    v-model="settingsStore.settings.auto_add_watching_channel_hashtag">
                </v-switch>
            </div>
            <div class="settings__item">
                <div class="settings__item-heading">デフォルトで表示される Twitter タブ内のタブ</div>
                <div class="settings__item-label">
                    視聴画面を開いたときに、パネルの Twitter タブの中で最初に表示されるタブを設定します。<br>
                </div>
                <v-select class="settings__item-form" color="primary" variant="outlined" hide-details
                    :density="is_form_dense ? 'compact' : 'default'"
                    :items="twitter_active_tab" v-model="settingsStore.settings.twitter_active_tab">
                </v-select>
            </div>
            <div class="settings__item">
                <div class="settings__item-heading">ツイートにつけるハッシュタグの位置</div>
                <div class="settings__item-label">
                    ハッシュタグをツイート本文のどの位置に追加するかを設定します。<br>
                </div>
                <v-select class="settings__item-form" color="primary" variant="outlined" hide-details
                    :density="is_form_dense ? 'compact' : 'default'"
                    :items="tweet_hashtag_position" v-model="settingsStore.settings.tweet_hashtag_position">
                </v-select>
            </div>
            <div class="settings__item">
                <div class="settings__item-heading">ツイートするキャプチャに番組タイトルの透かしを描画する</div>
                <div class="settings__item-label">
                    ツイートに添付するキャプチャ画像に、視聴中の番組タイトルを透かしとして描画するかを設定します。<br>
                    透かしの描画位置は 左上・右上・左下・右下 から選択できます。<br>
                </div>
                <v-select class="settings__item-form" color="primary" variant="outlined" hide-details
                    :density="is_form_dense ? 'compact' : 'default'"
                    :items="tweet_capture_watermark_position" v-model="settingsStore.settings.tweet_capture_watermark_position">
                </v-select>
            </div>
        </div>
        <v-overlay class="align-center justify-center" :persistent="true"
            :model-value="is_twitter_cookie_auth_sending" z-index="300">
            <v-progress-circular color="secondary" indeterminate size="64" />
        </v-overlay>
    </SettingsBase>
</template>
<script lang="ts">

import { mapStores } from 'pinia';
import { defineComponent } from 'vue';
import { VForm } from 'vuetify/components';

import Message from '@/message';
import Twitter, { ITwitterCookieAuthRequest } from '@/services/Twitter';
import useSettingsStore from '@/stores/SettingsStore';
import useUserStore from '@/stores/UserStore';
import Utils from '@/utils';
import SettingsBase from '@/views/Settings/Base.vue';

export default defineComponent({
    name: 'Settings-Twitter',
    components: {
        SettingsBase,
    },
    data() {
        return {

            // フォームを小さくするかどうか
            is_form_dense: Utils.isSmartphoneHorizontal(),

            // デフォルトで表示されるパネルのタブの選択肢
            twitter_active_tab: [
                {title: 'ツイート検索タブ', value: 'Search'},
                {title: 'タイムラインタブ', value: 'Timeline'},
                {title: 'キャプチャタブ', value: 'Capture'},
            ],

            // ツイートにつけるハッシュタグの位置の選択肢
            tweet_hashtag_position: [
                {title: 'ツイート本文の前に追加する', value: 'Prepend'},
                {title: 'ツイート本文の後に追加する', value: 'Append'},
                {title: 'ツイート本文の前に追加してから改行する', value: 'PrependWithLineBreak'},
                {title: 'ツイート本文の後に改行してから追加する', value: 'AppendWithLineBreak'},
            ],

            // ツイートするキャプチャに番組タイトルの透かしを描画する位置の選択肢
            tweet_capture_watermark_position: [
                {title: '透かしを描画しない', value: 'None'},
                {title: '透かしをキャプチャの左上に描画する', value: 'TopLeft'},
                {title: '透かしをキャプチャの右上に描画する', value: 'TopRight'},
                {title: '透かしをキャプチャの左下に描画する', value: 'BottomLeft'},
                {title: '透かしをキャプチャの右下に描画する', value: 'BottomRight'},
            ],

            // ローディング中かどうか
            is_loading: true,

            // Cookie 認証実行中かどうか
            is_twitter_cookie_auth_sending: false,

            // Cookie 認証用ダイヤログ
            twitter_cookie_auth_dialog: false,

            // Twitter の Cookie
            twitter_cookie: '',
        };
    },
    computed: {
        ...mapStores(useSettingsStore, useUserStore),
    },
    async created() {

        // アカウント情報を更新
        await this.userStore.fetchUser();

        // ローディング状態を解除
        this.is_loading = false;
    },
    methods: {
        async loginTwitterAccountWithCookieForm() {
            // ログインしていない場合はエラーにする
            if (this.userStore.is_logged_in === false) {
                Message.warning('連携をはじめるには、KonomiTV アカウントにログインしてください。');
                await Utils.sleep(0.01);
                this.twitter_cookie_auth_dialog = false;
                return;
            }
            this.twitter_cookie_auth_dialog = true;
        },

        async loginTwitterAccountWithCookie() {

            // バリデーションを実行
            if ((await (this.$refs.twitter_form as VForm).validate()).valid === false) {
                return;
            }

            // 空文字が入力されている場合は弾く
            if (this.twitter_cookie === null || this.twitter_cookie.trim() === '') {
                Message.warning('Cookie を入力してください！');
                return;
            }

            const twitter_auth_request: ITwitterCookieAuthRequest = {
                cookies_txt: this.twitter_cookie,
            };

            // Twitter 認証 API にリクエスト
            this.is_twitter_cookie_auth_sending = true;
            const result = await Twitter.auth(twitter_auth_request);
            this.is_twitter_cookie_auth_sending = false;
            if (result === false) {
                return;
            }

            // アカウント情報を強制的に更新
            await this.userStore.fetchUser(true);
            if (this.userStore.user === null) {
                Message.error('アカウント情報を取得できませんでした。');
                return;
            }

            // ログイン中のユーザーに紐づく Twitter アカウントのうち、一番 updated_at が新しいものを取得
            // ログインすると updated_at が更新されるため、この時点で一番 updated_at が新しいアカウントが今回連携したものだと判断できる
            // ref: https://stackoverflow.com/a/12192544/17124142 (ISO8601 のソートアルゴリズム)
            const current_twitter_account = [...this.userStore.user.twitter_accounts].sort((a, b) => {
                return (a.updated_at < b.updated_at) ? 1 : ((a.updated_at > b.updated_at) ? -1 : 0);
            })[0];

            Message.success(`Twitter @${current_twitter_account.screen_name} と連携しました。`);

            // フォームをリセットし、非表示にする
            (this.$refs.twitter_form as VForm).reset();
            this.twitter_cookie_auth_dialog = false;
        },

        async logoutTwitterAccount(screen_name: string) {

            // Twitter アカウント連携解除 API にリクエスト
            const result = await Twitter.logoutAccount(screen_name);
            if (result === false) {
                return;
            }

            // アカウント情報を強制的に更新
            await this.userStore.fetchUser(true);

            Message.success(`Twitter @${screen_name} との連携を解除しました。`);
        },
    }
});

</script>
<style lang="scss" scoped>

.settings__content {
    opacity: 1;
    transition: opacity 0.4s;

    &--loading {
        opacity: 0;
    }
}

.twitter-accounts {
    display: flex;
    flex-direction: column;
    padding: 20px 20px;
    border-radius: 15px;
    background: rgb(var(--v-theme-background-lighten-2));
    @include smartphone-horizontal {
        padding: 16px 20px;
        border-radius: 10px;
    }
    @include smartphone-vertical {
        padding: 16px 12px;
        border-radius: 10px;
    }

    &__heading {
        display: flex;
        align-items: center;
        font-size: 18px;
        font-weight: bold;
    }

    &__guide {
        display: flex;
        align-items: center;

        .text-h6 {
            @include tablet-vertical {
                font-size: 19px !important;
            }
            @include smartphone-vertical {
                font-size: 17px !important;
            }
        }

        svg {
            @include smartphone-horizontal-short {
                display: none;
            }
            @include smartphone-vertical {
                display: none;
            }
        }
        svg + div {
            @include smartphone-horizontal-short {
                margin-left: 0px !important;
            }
            @include smartphone-vertical {
                margin-left: 0px !important;
            }
        }
    }

    .twitter-account {
        display: flex;
        align-items: center;
        margin-top: 20px;
        @include smartphone-horizontal {
            margin-top: 16px;
        }

        &__icon {
            flex-shrink: 0;
            width: 70px;
            height: 70px;
            margin-right: 16px;
            border-radius: 50%;
            object-fit: cover;
            // 読み込まれるまでのアイコンの背景
            background: linear-gradient(150deg, rgb(var(--v-theme-gray)), rgb(var(--v-theme-background-lighten-2)));
            // 低解像度で表示する画像がぼやけないようにする
            // ref: https://sho-log.com/chrome-image-blurred/
            image-rendering: -webkit-optimize-contrast;
            @include smartphone-horizontal {
                width: 52px;
                height: 52px;
            }
            @include smartphone-vertical {
                width: 48px;
                height: 48px;
                margin-right: 10px;
            }
        }

        &__info {
            display: flex;
            flex-direction: column;
            min-width: 0;
            margin-right: 16px;
            @include smartphone-vertical {
                margin-right: 10px;
            }

            &-name {
                display: inline-flex;
                align-items: center;

                &-text {
                    display: inline-block;
                    color: rgb(var(--v-theme-text));
                    font-size: 20px;
                    font-weight: bold;
                    overflow: hidden;
                    white-space: nowrap;
                    text-overflow: ellipsis;  // はみ出た部分を … で省略
                    @include smartphone-horizontal {
                        font-size: 18px;
                    }
                    @include smartphone-vertical {
                        font-size: 16px;
                    }
                }
            }

            &-screen-name {
                display: inline-block;
                color: rgb(var(--v-theme-text-darken-1));
                font-size: 16px;
                @include smartphone-horizontal {
                    font-size: 14px;
                }
                @include smartphone-vertical {
                    font-size: 13.5px;
                }
            }
        }

        &__login {
            margin-top: 20px;
            margin-left: auto;
            margin-right: auto;
            border-radius: 7px;
            font-size: 15px;
            letter-spacing: 0;
            @include tablet-vertical {
                height: 42px !important;
                font-size: 14.5px;
            }
            @include smartphone-horizontal {
                height: 42px !important;
                font-size: 14.5px;
            }
            @include smartphone-vertical {
                height: 42px !important;
                font-size: 14.5px;
            }
        }

        &__logout {
            background: rgb(var(--v-theme-gray));
            border-radius: 7px;
            font-size: 15px;
            letter-spacing: 0;
            @include smartphone-horizontal {
                width: 116px !important;
            }
            @include smartphone-vertical {
                width: 100px !important;
                height: 48px !important;
                border-radius: 5px;
                font-size: 14px;
                svg {
                    width: 20px;
                    margin-right: 4px !important;
                }
            }
        }
    }
}

blockquote {
    border-left: 3px solid rgb(var(--v-theme-secondary));
    background-color: rgb(var(--v-theme-background-lighten-1));
    padding: 8px 12px;
    border-radius: 4px;
}

</style>
