import "./styles.css";
import App from "./App.svelte";
import HistoryApp from "./HistoryApp.svelte";
import { mount } from "svelte";

const historyView = new URLSearchParams(window.location.search).get("view") === "history" && new URLSearchParams(window.location.search).toString() === "view=history";
const app = mount(historyView ? HistoryApp : App, {
  target: document.getElementById("app") as HTMLElement
});

export default app;
