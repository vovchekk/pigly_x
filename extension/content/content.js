(function () {
  "use strict";

  const PIGLY_LOGO_SVG = `
    <svg viewBox="0 0 24 24" aria-hidden="true" class="r-1nao33i r-4qtqb9 r-yyyyoo r-1xvli5t r-dnmrzs r-bnwqim r-1plcrui r-lrvibr r-1hdv0qi">
      <g>
        <path d="M12 2C6.48 2 2 6.48 2 12c0 5.52 4.48 10 10 10s10-4.48 10-10C22 6.48 17.52 2 12 2zm1 14.5c-3.04 0-5.5-2.02-5.5-4.5S9.96 7.5 13 7.5s5.5 2.02 5.5 4.5-2.46 4.5-5.5 4.5zM13 10c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z"/>
      </g>
    </svg>
  `;

  // X's Tweet article selector
  const TWEET_SELECTOR = 'article[data-testid="tweet"]';
  const ACTION_GROUP_SELECTOR = '[role="group"][aria-label*="Reply"], [role="group"][aria-label*="Ответить"]';

  let activePanel = null;

  function initObserver() {
    processTweets();

    const observer = new MutationObserver((mutations) => {
      let shouldProcess = false;
      for (const mutation of mutations) {
        if (mutation.addedNodes.length > 0) {
          shouldProcess = true;
          break;
        }
      }
      if (shouldProcess) {
        processTweets();
      }
    });

    observer.observe(document.body, { childList: true, subtree: true });
  }

  function processTweets() {
    const tweets = document.querySelectorAll(TWEET_SELECTOR);
    tweets.forEach((tweet) => {
      if (tweet.dataset.piglyInjected) return;

      const actionGroup = tweet.querySelector(ACTION_GROUP_SELECTOR);
      if (!actionGroup) return; // Might be an ad or loading skeleton

      // Get text
      const textNode = tweet.querySelector('[data-testid="tweetText"]');
      const tweetText = textNode ? textNode.innerText : "";

      injectPiglyButton(tweet, actionGroup, tweetText);
    });
  }

  function injectPiglyButton(tweet, actionGroup, tweetText) {
    tweet.dataset.piglyInjected = "true";

    const wrapper = document.createElement("div");
    wrapper.className = "pigly-btn-wrapper";

    const btn = document.createElement("button");
    btn.className = "pigly-action-btn";
    btn.innerHTML = PIGLY_LOGO_SVG;
    btn.title = "Generate AI Reply with Pigly";

    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      e.preventDefault();
      togglePanel(wrapper, tweetText);
    });

    wrapper.appendChild(btn);

    // Append to the end of the action group
    // In X UI design, the action group contains items. We append as the last child wrapper.
    const lastChild = actionGroup.lastElementChild;
    if (lastChild && lastChild.parentNode) {
      actionGroup.appendChild(wrapper);
    }
  }

  function createPanel() {
    const panel = document.createElement("div");
    panel.className = "pigly-panel";
    panel.innerHTML = `
      <div class="pigly-panel-header">
        <div class="pigly-brand">
          <svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12c0 5.52 4.48 10 10 10s10-4.48 10-10C22 6.48 17.52 2 12 2zm1 14.5c-3.04 0-5.5-2.02-5.5-4.5S9.96 7.5 13 7.5s5.5 2.02 5.5 4.5-2.46 4.5-5.5 4.5zM13 10c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z"/></svg>
          AI Reply
        </div>
        <button class="pigly-panel-close">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12 19 6.41z"/></svg>
        </button>
      </div>
      <div class="pigly-panel-content"></div>
    `;

    panel.querySelector(".pigly-panel-close").addEventListener("click", (e) => {
      e.stopPropagation();
      closePanel();
    });

    // Prevent clicks from propagating to tweet (which opens the tweet overlay)
    panel.addEventListener("click", (e) => e.stopPropagation());

    return panel;
  }

  function closePanel() {
    if (activePanel) {
      activePanel.remove();
      activePanel = null;
    }
  }

  function renderLoading(container) {
    container.innerHTML = `
      <div class="pigly-loading">
        <div class="pigly-spinner"></div>
        <span>Generating ideas...</span>
      </div>
    `;
  }

  function renderError(container, message) {
    container.innerHTML = `
      <div class="pigly-error">${message || "An error occurred."}</div>
      <button class="pigly-btn-outline" style="margin-top: 10px; width: 100%;" id="pigly-auth-btn">Open Settings</button>
    `;

    const btn = container.querySelector("#pigly-auth-btn");
    btn.addEventListener("click", () => {
      // You can't open extension popups programmatically easily from content script
      // so we tell the background script or advise the user.
      alert("Please click the Pigly extension icon in your browser toolbar to log in.");
    });
  }

  function renderVariants(container, requestData, sourceTweetText) {
    if (!requestData || !requestData.results || requestData.results.length === 0) {
      renderError(container, "No variants generated.");
      return;
    }

    container.innerHTML = `<div class="pigly-variant-list"></div>`;
    const list = container.querySelector(".pigly-variant-list");

    requestData.results.forEach((res) => {
      const row = document.createElement("div");
      row.className = "pigly-variant";
      
      const txt = document.createElement("div");
      txt.className = "pigly-variant-text";
      txt.innerText = res.content;

      const actions = document.createElement("div");
      actions.className = "pigly-variant-actions";

      const btnCopy = document.createElement("button");
      btnCopy.className = "pigly-btn pigly-btn-outline";
      btnCopy.innerText = "Copy";
      btnCopy.addEventListener("click", () => {
        navigator.clipboard.writeText(res.content);
        btnCopy.innerText = "Copied!";
        setTimeout(() => { btnCopy.innerText = "Copy"; }, 2000);
      });

      const btnUse = document.createElement("button");
      btnUse.className = "pigly-btn";
      btnUse.innerText = "Reply";
      btnUse.addEventListener("click", () => {
        openNativeReply(sourceTweetText, res.content);
        closePanel();
      });

      actions.appendChild(btnCopy);
      actions.appendChild(btnUse);

      row.appendChild(txt);
      row.appendChild(actions);
      list.appendChild(row);
    });
  }

  function openNativeReply(sourceTweetText, replyText) {
    // 1. Find the native reply button for this tweet and click it to open the composer modal
    // Because DOM nodes change, let's find the tweet containing the text
    const tweets = document.querySelectorAll(TWEET_SELECTOR);
    let targetTweet = null;
    for (const t of tweets) {
      const txtNode = t.querySelector('[data-testid="tweetText"]');
      if (txtNode && txtNode.innerText === sourceTweetText) {
        targetTweet = t;
        break;
      }
    }

    if (targetTweet) {
      const replyBtn = targetTweet.querySelector('[data-testid="reply"]');
      if (replyBtn) {
        replyBtn.click();
        
        // Wait for composer to appear
        setTimeout(() => {
          injectTextIntoComposer(replyText);
        }, 500);
        return;
      }
    }
    
    // Fallback if composer is already focused/open
    injectTextIntoComposer(replyText);
  }

  function injectTextIntoComposer(text) {
    const composer = document.querySelector('div[data-testid="tweetTextarea_0"]');
    if (!composer) {
      navigator.clipboard.writeText(text);
      alert("Could not find the reply textarea. The text has been copied to your clipboard.");
      return;
    }

    composer.focus();
    // Use execCommand to simulate real typing (Draft.js needs this)
    document.execCommand('insertText', false, text);
  }

  async function togglePanel(wrapperNode, tweetText) {
    if (activePanel && activePanel.parentNode === wrapperNode) {
      closePanel();
      return;
    }

    closePanel(); // Close any other open panel

    const panel = createPanel();
    wrapperNode.appendChild(panel);
    activePanel = panel;

    // Use requestAnimationFrame for CSS transition
    requestAnimationFrame(() => {
      panel.classList.add("show");
    });

    const contentBox = panel.querySelector(".pigly-panel-content");
    renderLoading(contentBox);

    try {
      chrome.runtime.sendMessage({ action: "getSession" }, (sessionRes) => {
        if (!sessionRes || !sessionRes.authenticated) {
          renderError(contentBox, "Please log in to Pigly first.");
          return;
        }

        // Fetch variants
        chrome.runtime.sendMessage(
          { action: "reply", payload: { text: tweetText, context: "" } },
          (response) => {
            if (response && response.ok) {
              renderVariants(contentBox, response.data.request, tweetText);
            } else {
              renderError(contentBox, response?.error?.message || "Failed to generate.");
            }
          }
        );
      });
    } catch (err) {
      renderError(contentBox, "Extension disconnected. Please reload the page.");
    }
  }

  // Close panel on outside click
  document.addEventListener("click", () => {
    closePanel();
  });

  // Start
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initObserver);
  } else {
    initObserver();
  }

})();
