(() => {
  "use strict";

  const menuButton = document.querySelector(".menu-toggle");
  const navigation = document.querySelector("#navigation");
  const setMenuOpen = (open) => {
    navigation.classList.toggle("is-open", open);
    menuButton.setAttribute("aria-expanded", String(open));
    menuButton.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
  };

  menuButton.addEventListener("click", () => {
    setMenuOpen(menuButton.getAttribute("aria-expanded") !== "true");
  });
  navigation.addEventListener("click", (event) => {
    if (event.target.closest("a")) setMenuOpen(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && menuButton.getAttribute("aria-expanded") === "true") {
      setMenuOpen(false);
      menuButton.focus();
    }
  });

  const tabs = [...document.querySelectorAll('[role="tab"]')];
  const selectTab = (selected, focus = false) => {
    tabs.forEach((tab) => {
      const active = tab === selected;
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
      document.getElementById(tab.getAttribute("aria-controls")).hidden = !active;
    });
    if (focus) selected.focus();
  };
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => selectTab(tab));
    tab.addEventListener("keydown", (event) => {
      let nextIndex;
      if (event.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
      if (event.key === "ArrowLeft") nextIndex = (index - 1 + tabs.length) % tabs.length;
      if (event.key === "Home") nextIndex = 0;
      if (event.key === "End") nextIndex = tabs.length - 1;
      if (nextIndex !== undefined) {
        event.preventDefault();
        selectTab(tabs[nextIndex], true);
      }
    });
  });

  const themeButton = document.querySelector(".theme-toggle");
  const themeMeta = document.querySelector('meta[name="theme-color"]');
  const setTheme = (light) => {
    document.body.classList.toggle("light-theme", light);
    themeButton.setAttribute("aria-pressed", String(light));
    themeButton.setAttribute("aria-label", `Switch to ${light ? "dark" : "light"} theme`);
    themeMeta.setAttribute("content", light ? "#f3f7f3" : "#09120c");
  };
  try {
    setTheme(localStorage.getItem("rasam-landing-theme") === "light");
  } catch {
    setTheme(false);
  }
  themeButton.addEventListener("click", () => {
    const light = !document.body.classList.contains("light-theme");
    setTheme(light);
    try {
      localStorage.setItem("rasam-landing-theme", light ? "light" : "dark");
    } catch {
      // Theme switching still works when browser storage is unavailable.
    }
  });

  const openLinkedQuestion = () => {
    if (window.location.hash === "#learning-faq") {
      document.getElementById("learning-faq").open = true;
    }
  };
  window.addEventListener("hashchange", openLinkedQuestion);
  document.querySelectorAll('a[href="#learning-faq"]').forEach((link) => {
    link.addEventListener("click", () => {
      document.getElementById("learning-faq").open = true;
    });
  });
  openLinkedQuestion();
})();
