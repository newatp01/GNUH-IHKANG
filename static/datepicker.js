(function () {
  var WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];
  var MONTHS_KO = function (y, m) { return y + "년 " + m + "월"; };
  var openPanel = null;

  function pad(n) { return n < 10 ? "0" + n : "" + n; }
  function fmt(y, m, d) { return y + "-" + pad(m) + "-" + pad(d); }

  function closePanel() {
    if (openPanel) {
      openPanel.remove();
      openPanel = null;
    }
  }

  function buildPanel(input) {
    var initial = input.value ? new Date(input.value + "T00:00:00") : new Date();
    var state = { y: initial.getFullYear(), m: initial.getMonth() + 1 };

    var panel = document.createElement("div");
    panel.className = "bigdate-panel";

    function render() {
      panel.innerHTML = "";

      var header = document.createElement("div");
      header.className = "bigdate-header";

      var prev = document.createElement("button");
      prev.type = "button";
      prev.className = "bigdate-nav";
      prev.textContent = "‹";
      prev.addEventListener("click", function (e) {
        e.stopPropagation();
        state.m -= 1;
        if (state.m < 1) { state.m = 12; state.y -= 1; }
        render();
      });

      var label = document.createElement("span");
      label.className = "bigdate-label";
      label.textContent = MONTHS_KO(state.y, state.m);

      var next = document.createElement("button");
      next.type = "button";
      next.className = "bigdate-nav";
      next.textContent = "›";
      next.addEventListener("click", function (e) {
        e.stopPropagation();
        state.m += 1;
        if (state.m > 12) { state.m = 1; state.y += 1; }
        render();
      });

      header.appendChild(prev);
      header.appendChild(label);
      header.appendChild(next);
      panel.appendChild(header);

      var weekRow = document.createElement("div");
      weekRow.className = "bigdate-grid bigdate-weekrow";
      WEEKDAYS.forEach(function (w) {
        var s = document.createElement("span");
        s.textContent = w;
        weekRow.appendChild(s);
      });
      panel.appendChild(weekRow);

      var firstDay = new Date(state.y, state.m - 1, 1);
      var startOffset = firstDay.getDay();
      var daysInMonth = new Date(state.y, state.m, 0).getDate();

      var grid = document.createElement("div");
      grid.className = "bigdate-grid";

      for (var i = 0; i < startOffset; i++) {
        var blank = document.createElement("span");
        grid.appendChild(blank);
      }
      var todayStr = fmt(new Date().getFullYear(), new Date().getMonth() + 1, new Date().getDate());
      for (var d = 1; d <= daysInMonth; d++) {
        (function (day) {
          var btn = document.createElement("button");
          btn.type = "button";
          btn.className = "bigdate-day";
          var vs = fmt(state.y, state.m, day);
          if (vs === input.value) btn.classList.add("selected");
          if (vs === todayStr) btn.classList.add("today");
          btn.textContent = day;
          btn.addEventListener("click", function (e) {
            e.stopPropagation();
            input.value = vs;
            input.dispatchEvent(new Event("change", { bubbles: true }));
            closePanel();
          });
          grid.appendChild(btn);
        })(d);
      }
      panel.appendChild(grid);
    }

    render();
    return panel;
  }

  function openFor(input) {
    if (openPanel && openPanel._forInput === input) { closePanel(); return; }
    closePanel();
    var panel = buildPanel(input);
    panel._forInput = input;
    document.body.appendChild(panel);
    openPanel = panel;

    var rect = input.getBoundingClientRect();
    panel.style.position = "absolute";
    panel.style.top = (window.scrollY + rect.bottom + 6) + "px";
    panel.style.left = (window.scrollX + rect.left) + "px";
  }

  document.addEventListener("click", function (e) {
    if (e.target.matches("[data-datepicker]")) {
      openFor(e.target);
    } else if (openPanel && !openPanel.contains(e.target)) {
      closePanel();
    }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closePanel();
  });
})();
