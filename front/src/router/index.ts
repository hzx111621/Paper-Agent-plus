import { createRouter, createWebHistory } from "vue-router";

import SessionWorkspaceView from "../views/SessionWorkspaceView.vue";
import SystemSettingsView from "../views/SystemSettingsView.vue";
import LibraryView from "../views/LibraryView.vue";
import AccountSettingsView from "../views/AccountSettingsView.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      redirect: "/sessions",
    },
    {
      path: "/sessions",
      name: "sessions",
      component: SessionWorkspaceView,
    },
    {
      path: "/settings",
      name: "settings",
      component: SystemSettingsView,
    },
    { path: "/library", name: "library", component: LibraryView },
    { path: "/account", name: "account", component: AccountSettingsView },
  ],
});

export default router;
