import "./styles.css";
import "./app.css";
import App from "./App.svelte";
import PanelApp from "./PanelApp.svelte";
import { installContextMenuGuard } from "./domain/contextMenuGuard";
import { mount } from "svelte";

installContextMenuGuard();

const search = new URLSearchParams(window.location.search);
const query = window.location.search.replace(/^\?/, "");
const panelView = search.get("view") === "panel" && query === "view=panel";
const app = mount(panelView ? PanelApp : App, {
  target: document.getElementById("app") as HTMLElement
});

export default app;
