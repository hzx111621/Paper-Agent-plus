<script setup lang="ts">
import { LoaderCircle, LogIn, UserPlus } from "lucide-vue-next";
import { computed, ref } from "vue";

import { loginAccount, registerAccount } from "../api/auth";
import type { AuthUser } from "../types/auth";

const emit = defineEmits<{
  authenticated: [user: AuthUser];
}>();

const mode = ref<"login" | "register">("login");
const username = ref("");
const password = ref("");
const submitting = ref(false);
const errorMessage = ref("");

const isRegistering = computed(() => mode.value === "register");

async function submit() {
  if (submitting.value) {
    return;
  }
  errorMessage.value = "";
  submitting.value = true;
  try {
    const payload = isRegistering.value
      ? await registerAccount(username.value.trim(), password.value)
      : await loginAccount(username.value.trim(), password.value);
    emit("authenticated", payload.user);
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "操作失败，请稍后再试";
  } finally {
    submitting.value = false;
  }
}

function switchMode(nextMode: "login" | "register") {
  mode.value = nextMode;
  errorMessage.value = "";
}
</script>

<template>
  <main class="auth-page">
    <section class="auth-panel" aria-labelledby="auth-title">
      <div class="auth-brand">
        <img src="/university-emblem.jpeg" alt="华东理工大学校徽" />
        <div>
          <span class="eyebrow">Paper-Agent++</span>
          <strong>Research Workspace</strong>
        </div>
      </div>

      <div class="auth-heading">
        <span class="auth-kicker">Personal Workspace</span>
        <h1 id="auth-title">{{ isRegistering ? "创建你的研究账户" : "登录研究工作台" }}</h1>
        <p>{{ isRegistering ? "注册后，你的论文会话和设置将保存在自己的账户下。" : "登录后继续管理你的论文调研会话。" }}</p>
      </div>

      <form class="auth-form" @submit.prevent="submit">
        <label class="field-group">
          <span>用户名</span>
          <input v-model="username" class="field" type="text" autocomplete="username" placeholder="输入用户名" required />
        </label>
        <label class="field-group">
          <span>密码</span>
          <input v-model="password" class="field" type="password" autocomplete="current-password" placeholder="至少 6 个字符" required />
        </label>

        <p v-if="errorMessage" class="auth-error" role="alert">{{ errorMessage }}</p>

        <button class="button primary auth-submit" type="submit" :disabled="submitting">
          <LoaderCircle v-if="submitting" class="spinning" :size="17" />
          <UserPlus v-else-if="isRegistering" :size="17" />
          <LogIn v-else :size="17" />
          {{ submitting ? "处理中" : isRegistering ? "注册并登录" : "登录" }}
        </button>
      </form>

      <div class="auth-switch">
        <span>{{ isRegistering ? "已经有账户？" : "还没有账户？" }}</span>
        <button type="button" @click="switchMode(isRegistering ? 'login' : 'register')">
          {{ isRegistering ? "返回登录" : "注册账户" }}
        </button>
      </div>
    </section>
  </main>
</template>
