<script setup lang="ts">
import {
  ChevronLeft,
  History,
  LoaderCircle,
  LogOut,
  MessageSquareText,
  PanelsTopLeft,
  Plus,
  Trash2,
  UserRound,
  Workflow,
  Library,
} from "lucide-vue-next";
import { computed, ref } from "vue";
import { RouterLink, useRoute } from "vue-router";

import type { SessionStatus, SessionSummary } from "../types/sessions";
import type { AuthUser } from "../types/auth";

const props = defineProps<{
  collapsed: boolean;
  sessions: SessionSummary[];
  selectedKey: string;
  loadingSessions: boolean;
  creatingSession: boolean;
  currentUser: AuthUser;
}>();

const emit = defineEmits<{
  toggle: [];
  createSession: [];
  selectSession: [sessionKey: string];
  removeSession: [sessionKey: string];
  renameSession: [sessionKey: string];
  archiveSession: [sessionKey: string];
  logout: [];
}>();

const route = useRoute();
const userMenuOpen = ref(false);

const groupedSessions = computed(() => {
  const groups = [
    { key: "today", label: "今天", sessions: [] as SessionSummary[] },
    { key: "week", label: "本周", sessions: [] as SessionSummary[] },
    { key: "earlier", label: "更早", sessions: [] as SessionSummary[] },
  ];

  for (const session of props.sessions) {
    const bucket = sessionBucket(session.updated_at);
    const group = groups.find((item) => item.key === bucket) ?? groups[2];
    group.sessions.push(session);
  }

  return groups.filter((group) => group.sessions.length > 0);
});

const compactSessions = computed(() => props.sessions.slice(0, 6));

/** 中文注释：把会话按更新时间分成几个简单区域，让历史列表更像“最近对话”，不会一长串看不清。 */
function sessionBucket(value: string) {
  const updatedAt = new Date(value);
  if (Number.isNaN(updatedAt.getTime())) {
    return "earlier";
  }

  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const updatedStart = new Date(updatedAt.getFullYear(), updatedAt.getMonth(), updatedAt.getDate()).getTime();
  const dayGap = Math.floor((todayStart - updatedStart) / 86_400_000);

  if (dayGap <= 0) {
    return "today";
  }
  if (dayGap < 7) {
    return "week";
  }
  return "earlier";
}

/** 中文注释：侧栏空间有限，所以时间只显示用户最容易理解的短格式。 */
function formatUpdatedAt(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "刚刚";
  }

  const now = new Date();
  const isToday = date.toDateString() === now.toDateString();
  if (isToday) {
    return new Intl.DateTimeFormat("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  }

  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
  }).format(date);
}

function statusLabel(status: SessionStatus) {
  if (status === "running") {
    return "运行中";
  }
  if (status === "cancel_requested") {
    return "正在停止";
  }
  if (status === "cancelled") {
    return "已停止";
  }
  if (status === "completed") {
    return "已完成";
  }
  if (status === "failed") {
    return "失败";
  }
  return "未开始";
}
</script>

<template>
  <aside class="sidebar" :data-collapsed="collapsed">
    <div class="sidebar-head">
      <div class="brand-lockup">
        <div class="brand-mark brand-mark-image">
          <img src="/university-emblem.jpeg" alt="华东理工大学校徽" />
        </div>
        <div v-if="!collapsed" class="brand-copy">
          <span class="eyebrow">Papers Agents</span>
          <strong>Console</strong>
        </div>
      </div>
      <button
        class="icon-button"
        type="button"
        :aria-label="collapsed ? '展开导航' : '收起导航'"
        @click="emit('toggle')"
      >
        <ChevronLeft :size="16" :class="{ rotated: collapsed }" />
      </button>
    </div>

    <nav class="sidebar-nav" aria-label="主导航">
      <RouterLink
        class="nav-item"
        :class="{ active: route.name === 'sessions' }"
        to="/sessions"
      >
        <Workflow :size="18" />
        <span v-if="!collapsed">会话工作台</span>
      </RouterLink>

      <RouterLink class="nav-item" :class="{ active: route.name === 'library' }" to="/library">
        <Library :size="18" />
        <span v-if="!collapsed">论文资料库</span>
      </RouterLink>

      <RouterLink
        class="nav-item"
        :class="{ active: route.name === 'settings' }"
        to="/settings"
      >
        <PanelsTopLeft :size="18" />
        <span v-if="!collapsed">系统配置</span>
      </RouterLink>

      <RouterLink class="nav-item" :class="{ active: route.name === 'account' }" to="/account">
        <UserRound :size="18" />
        <span v-if="!collapsed">账户与安全</span>
      </RouterLink>
    </nav>

    <section class="sidebar-history" aria-label="历史会话">
      <div v-if="!collapsed" class="sidebar-history-head">
        <div>
          <span class="eyebrow">History</span>
          <h2>历史会话</h2>
        </div>
        <button
          class="icon-button sidebar-history-create"
          type="button"
          :disabled="creatingSession"
          aria-label="新建会话"
          @click="emit('createSession')"
        >
          <LoaderCircle v-if="creatingSession" class="spinning" :size="15" />
          <Plus v-else :size="16" />
        </button>
      </div>

      <div v-if="collapsed" class="sidebar-history-compact">
        <button
          class="icon-button sidebar-history-create"
          type="button"
          :disabled="creatingSession"
          aria-label="新建会话"
          @click="emit('createSession')"
        >
          <LoaderCircle v-if="creatingSession" class="spinning" :size="15" />
          <Plus v-else :size="16" />
        </button>

        <button
          v-for="session in compactSessions"
          :key="session.key"
          class="sidebar-session-mini"
          type="button"
          :class="{ active: session.key === selectedKey }"
          :data-status="session.status"
          :aria-label="`打开会话：${session.title}`"
          @click="emit('selectSession', session.key)"
        >
          <MessageSquareText :size="16" />
        </button>
      </div>

      <template v-else>
        <div v-if="loadingSessions" class="sidebar-history-state">
          <LoaderCircle class="spinning" :size="16" />
          <span>正在加载历史…</span>
        </div>

        <div v-else-if="!sessions.length" class="sidebar-history-state">
          <History :size="16" />
          <span>暂无历史，先新建一个主题。</span>
        </div>

        <div v-else class="sidebar-session-list">
          <div v-for="group in groupedSessions" :key="group.key" class="sidebar-session-group">
            <span class="sidebar-session-group-title">{{ group.label }}</span>
            <div
              v-for="session in group.sessions"
              :key="session.key"
              class="sidebar-session-item"
              role="button"
              tabindex="0"
              :class="{ active: session.key === selectedKey }"
              :data-status="session.status"
              :data-archived="session.archived"
              @click="emit('selectSession', session.key)"
              @keydown.enter.prevent="emit('selectSession', session.key)"
              @keydown.space.prevent="emit('selectSession', session.key)"
            >
              <span class="sidebar-session-accent" aria-hidden="true"></span>
              <span class="sidebar-session-main">
                <span class="sidebar-session-title">{{ session.title || '未命名会话' }}</span>
                <span class="sidebar-session-preview">{{ session.preview || '等待输入主题' }}</span>
                <span class="sidebar-session-meta">
                  <span class="sidebar-session-status-dot" aria-hidden="true"></span>
                  <span>{{ statusLabel(session.status) }}</span>
                  <span>·</span>
                  <span>{{ formatUpdatedAt(session.updated_at) }}</span>
                </span>
              </span>
              <button
                class="sidebar-session-action"
                type="button"
                aria-label="重命名会话"
                @click.stop="emit('renameSession', session.key)"
              >
                重命名
              </button>
              <button
                class="sidebar-session-action"
                type="button"
                :aria-label="session.archived ? '恢复会话' : '归档会话'"
                @click.stop="emit('archiveSession', session.key)"
              >
                {{ session.archived ? '恢复' : '归档' }}
              </button>
              <button
                class="sidebar-session-delete"
                type="button"
                aria-label="删除会话"
                @click.stop="emit('removeSession', session.key)"
              >
                <Trash2 :size="13" />
                <span>删除</span>
              </button>
            </div>
          </div>
        </div>
      </template>
    </section>

    <!-- 底部固定用户信息，给工作台保留一个稳定的个人入口。 -->
    <div v-if="!collapsed" class="sidebar-user-wrap">
      <button
        class="sidebar-user"
        type="button"
        :aria-expanded="userMenuOpen"
        aria-label="打开账户菜单"
        @click="userMenuOpen = !userMenuOpen"
      >
      <span class="sidebar-user-avatar"><UserRound :size="16" /></span>
      <span class="sidebar-user-copy"><strong>{{ currentUser.username }}</strong><small>本地账户</small></span>
      <ChevronLeft class="sidebar-user-chevron" :size="14" />
      </button>
      <div v-if="userMenuOpen" class="sidebar-user-menu">
        <div class="sidebar-user-menu-name">{{ currentUser.username }}</div>
        <button type="button" @click="emit('logout'); userMenuOpen = false">
          <LogOut :size="14" />
          退出登录
        </button>
      </div>
    </div>
  </aside>
</template>
