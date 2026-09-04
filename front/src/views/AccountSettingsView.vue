<script setup lang="ts">
import { onMounted, ref } from "vue";
import { changePassword, deleteAccount, getCurrentUser, listAuthTokens, requestPasswordReset, resetPassword, revokeOtherTokens } from "../api/auth";
import { clearAuthToken } from "../api/auth";
import { pushToast } from "../stores/notifications";
import { useRouter } from "vue-router";

const router = useRouter();
const username = ref("");
const oldPassword = ref("");
const newPassword = ref("");
const resetCode = ref("");
const resetPasswordValue = ref("");
const tokenCount = ref(0);
const tokens = ref<Array<{ created_at: string; expires_at: string }>>([]);

onMounted(async () => {
  try {
    username.value = (await getCurrentUser()).user.username;
    const payload = await listAuthTokens();
    tokens.value = payload.tokens;
    tokenCount.value = payload.tokens.length;
  } catch (error) { pushToast({ tone: "error", title: "加载账户安全信息失败", description: error instanceof Error ? error.message : "请稍后再试" }); }
});

async function savePassword() {
  try { await changePassword(oldPassword.value, newPassword.value); oldPassword.value = ""; newPassword.value = ""; pushToast({ tone: "success", title: "密码已修改", description: "其他登录设备已退出。" }); }
  catch (error) { pushToast({ tone: "error", title: "修改密码失败", description: error instanceof Error ? error.message : "请稍后再试" }); }
}

async function makeResetCode() {
  try { const payload = await requestPasswordReset(username.value); resetCode.value = payload.reset_code; pushToast({ tone: "info", title: "恢复码已生成", description: "本地版不会发送邮件，恢复码已填入下方表单。" }); }
  catch (error) { pushToast({ tone: "error", title: "生成恢复码失败", description: error instanceof Error ? error.message : "请稍后再试" }); }
}

async function doReset() {
  try { await resetPassword(username.value, resetCode.value, resetPasswordValue.value); resetCode.value = ""; resetPasswordValue.value = ""; pushToast({ tone: "success", title: "密码已重置", description: "请使用新密码重新登录。" }); }
  catch (error) { pushToast({ tone: "error", title: "重置密码失败", description: error instanceof Error ? error.message : "请稍后再试" }); }
}

async function revokeOthers() {
  try { await revokeOtherTokens(); tokenCount.value = 1; tokens.value = tokens.value.slice(0, 1); pushToast({ tone: "success", title: "其他设备已退出", description: "当前浏览器仍保持登录。" }); }
  catch (error) { pushToast({ tone: "error", title: "撤销设备失败", description: error instanceof Error ? error.message : "请稍后再试" }); }
}

async function removeAccount() {
  const password = window.prompt("请输入当前密码确认删除账户");
  if (password === null) return;
  try { await deleteAccount(password); clearAuthToken(); await router.replace({ name: "sessions" }); window.location.reload(); }
  catch (error) { pushToast({ tone: "error", title: "删除账户失败", description: error instanceof Error ? error.message : "请稍后再试" }); }
}
</script>

<template>
  <section class="page-shell account-shell"><header class="hero-card"><div class="hero-copy"><span class="eyebrow">Account Security</span><h1>账户与安全</h1><p>{{ username }} 的登录设备、密码和账户数据管理。</p></div></header><section class="account-grid"><article class="editor-card"><h2>修改密码</h2><label class="field-group"><span>原密码</span><input v-model="oldPassword" class="field" type="password" /></label><label class="field-group"><span>新密码</span><input v-model="newPassword" class="field" type="password" /></label><button class="button primary" type="button" @click="savePassword">保存新密码</button></article><article class="editor-card"><h2>找回密码</h2><p class="mini-note">本地版通过一次性恢复码找回，不会发送邮件。</p><button class="button secondary" type="button" @click="makeResetCode">生成恢复码</button><input v-model="resetCode" class="field" placeholder="恢复码" /><input v-model="resetPasswordValue" class="field" type="password" placeholder="新密码" /><button class="button primary" type="button" @click="doReset">重置密码</button></article><article class="editor-card"><h2>登录设备 <small>{{ tokenCount }} 个令牌</small></h2><div v-for="token in tokens" :key="token.created_at" class="token-row"><span>登录于 {{ new Date(token.created_at).toLocaleString('zh-CN') }}</span><small>有效期至 {{ new Date(token.expires_at).toLocaleString('zh-CN') }}</small></div><button class="button secondary" type="button" @click="revokeOthers">退出其他设备</button></article><article class="editor-card danger-zone"><h2>删除账户</h2><p>删除后会话、论文库、笔记和上传文件都会被永久删除。</p><button class="button danger" type="button" @click="removeAccount">永久删除账户</button></article></section></section>
</template>
