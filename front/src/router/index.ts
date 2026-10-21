import { createRouter, createWebHistory } from "vue-router";

import SessionWorkspaceView from "../views/SessionWorkspaceView.vue";
import SystemSettingsView from "../views/SystemSettingsView.vue";
import LibraryView from "../views/LibraryView.vue";

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
  ],
});

export default router;
