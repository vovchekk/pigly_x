(function () {
  "use strict";

  const PIGLY_LOGO_SVG = `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 2C6.48 2 2 6.48 2 12c0 5.52 4.48 10 10 10s10-4.48 10-10C22 6.48 17.52 2 12 2zm1 14.5c-3.04 0-5.5-2.02-5.5-4.5S9.96 7.5 13 7.5s5.5 2.02 5.5 4.5-2.46 4.5-5.5 4.5zM13 10c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z"></path>
    </svg>
  `;
  const REFRESH_ICON_SVG = `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M17.65 6.35A7.95 7.95 0 0 0 12 4V1L7 6l5 5V7a5 5 0 1 1-5 5H5a7 7 0 1 0 12.65-5.65z"></path>
    </svg>
  `;
  const TRANSLATE_ICON_SVG = `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12.87 15.07 11 11l-1.87 4.07h3.74ZM18.5 4h-5V2.5a.5.5 0 0 0-1 0V4h-7a.5.5 0 0 0 0 1H11c-.07 1.83-.64 3.54-1.63 5A13.06 13.06 0 0 1 7.3 7.76a.5.5 0 1 0-.8.6 14.1 14.1 0 0 0 2.25 2.44A13 13 0 0 1 5.4 13.8a.5.5 0 1 0 .4.92 14.14 14.14 0 0 0 3.76-3.12 13.88 13.88 0 0 0 1.66 1.16.5.5 0 0 0 .56-.83c-.5-.34-.98-.72-1.41-1.13 1.18-1.66 1.87-3.68 1.94-5.8h2.66a.5.5 0 0 0 0-1ZM19.95 20.78l-3.84-8.35a.5.5 0 0 0-.9 0l-3.84 8.35a.5.5 0 0 0 .91.42l1.3-2.83h4.26l1.3 2.83a.5.5 0 1 0 .91-.42Z"></path>
    </svg>
  `;
  const SHORTEN_ICON_SRC = chrome.runtime.getURL("images/lupa.png");
  const COMMENT_ICON_SRC = chrome.runtime.getURL("images/comment.png");

  const TWEET_SELECTOR = 'article[data-testid="tweet"]';
  const TWEET_TEXT_SELECTOR = '[data-testid="tweetText"]';
  const USER_NAME_SELECTOR = '[data-testid="User-Name"]';
  const COMPOSER_SELECTOR = 'div[data-testid="tweetTextarea_0"]';
  const COMPOSER_CONTAINER_SELECTOR = '[data-testid="tweetTextarea_0RichTextInputContainer"]';
  const TOOLBAR_SELECTOR = 'div[data-testid="toolBar"]';
  const INLINE_ACTIONS_SELECTOR = 'div[role="group"]';
  const REPLYING_TO_SELECTOR = 'div[data-testid="replyTo"]';

  let activePanel = null;
  let activePanelAnchor = null;
  let activePanelMode = null;
  let activePanelPlacement = null;
  let activePanelScrollSnapshot = null;
  const generationCache = new Map();
  const GENERATION_CACHE_TTL_MS = 90 * 1000;
  let featureState = {
    replies: true,
    shorten: true,
    translate: false
  };
  let shortenerTriggerLength = 200;
  const DEFAULT_SHORTENER_TRIGGER_LENGTH = 200;

  function getCachedGeneration(cacheKey) {
    const entry = generationCache.get(cacheKey);
    if (!entry) return null;
    if (Date.now() - entry.createdAt > GENERATION_CACHE_TTL_MS) {
      generationCache.delete(cacheKey);
      return null;
    }
    entry.lastAccessAt = Date.now();
    return entry.request;
  }

  function setCachedGeneration(cacheKey, request) {
    generationCache.set(cacheKey, {
      request,
      createdAt: Date.now(),
      lastAccessAt: Date.now()
    });
  }

  function pruneGenerationCache() {
    const now = Date.now();
    generationCache.forEach((entry, key) => {
      if (!entry || now - (entry.lastAccessAt || entry.createdAt || 0) > GENERATION_CACHE_TTL_MS) {
        generationCache.delete(key);
      }
    });
  }

  function init() {
    loadFeatures(() => {
      loadUserDefaults(() => {
        processPage();
        observeDom();
      });
    });

    document.addEventListener("click", (event) => {
      if (activePanel && !activePanel.contains(event.target)) {
        closePanel();
      }
    });

    window.addEventListener("resize", refreshActivePanelPosition);
    window.addEventListener("scroll", handleActivePanelScroll, true);

    if (chrome.storage && chrome.storage.onChanged) {
      chrome.storage.onChanged.addListener((changes, areaName) => {
        if (areaName !== "local" || !changes.pigly_features) return;
        const nextFeatures = changes.pigly_features.newValue || {};
        featureState = {
          replies: nextFeatures.replies !== false,
          shorten: nextFeatures.shorten !== false,
          translate: nextFeatures.translate === true
        };
        resetInjectedUi();
        processPage();
      });
    }

    if (chrome.storage && chrome.storage.onChanged) {
      chrome.storage.onChanged.addListener((changes, areaName) => {
        if (areaName !== "local" || !changes.pigly_user) return;
        syncTranslateFeature(changes.pigly_user.newValue?.defaults);
        shortenerTriggerLength = resolveShortenerTriggerLength(changes.pigly_user.newValue?.defaults);
        resetInjectedUi();
        processPage();
      });
    }
  }

  function loadFeatures(callback) {
    try {
      chrome.storage.local.get(["pigly_features"], (result) => {
        const nextFeatures = result.pigly_features || {};
        featureState = {
          replies: nextFeatures.replies !== false,
          shorten: nextFeatures.shorten !== false,
          translate: nextFeatures.translate === true
        };
        callback();
      });
    } catch (_error) {
      callback();
    }
  }

  function loadUserDefaults(callback) {
    try {
      chrome.storage.local.get(["pigly_user"], (result) => {
        syncTranslateFeature(result.pigly_user?.defaults);
        shortenerTriggerLength = resolveShortenerTriggerLength(result.pigly_user?.defaults);
        callback();
      });
    } catch (_error) {
      callback();
    }
  }

  function observeDom() {
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.addedNodes.length > 0) {
          processPage();
          break;
        }
      }
    });

    observer.observe(document.body, { childList: true, subtree: true });
  }

  function processPage() {
    if (featureState.shorten) {
      injectShortenButtons();
    }
    if (featureState.replies || featureState.translate) {
      injectReplyComposerButtons();
    }
  }

  function syncTranslateFeature(defaults) {
    featureState.translate = !!defaults?.translate_enabled;
  }

  function resetInjectedUi() {
    closePanel();
    document.querySelectorAll(".pigly-inline-wrapper, .pigly-composer-wrapper").forEach((node) => node.remove());
    document.querySelectorAll(TWEET_SELECTOR).forEach((tweet) => delete tweet.dataset.piglyShortenInjected);
    document.querySelectorAll("[data-pigly-reply-root]").forEach((node) => {
      delete node.dataset.piglyReplyRoot;
      node.removeAttribute("data-pigly-reply-root");
    });
  }

  function injectShortenButtons() {
    document.querySelectorAll(TWEET_SELECTOR).forEach((tweet) => {
      if (tweet.dataset.piglyShortenInjected === "true") return;
      if (shouldSkipShortenForTweet(tweet)) return;
      const tweetText = extractTweetText(tweet);
      const userNameBlock = tweet.querySelector(USER_NAME_SELECTOR);
      if (!tweetText || !userNameBlock) return;
      if (!shouldShowShortenButton(tweet, tweetText)) return;
      const mountTarget = findShortenMount(tweet, userNameBlock);
      if (!mountTarget || !mountTarget.node) return;

      tweet.dataset.piglyShortenInjected = "true";

      const wrapper = document.createElement("span");
      wrapper.className = "pigly-inline-wrapper";

      const button = document.createElement("button");
      button.type = "button";
      button.className = "pigly-inline-trigger";
      button.title = "Shorten this post with Pigly";
      button.setAttribute("aria-label", "Shorten this post with Pigly");
      button.innerHTML = `<img src="${SHORTEN_ICON_SRC}" alt="" class="pigly-trigger-icon">`;
      bindTriggerGuards(button);

      button.addEventListener("click", async (event) => {
        event.preventDefault();
        event.stopPropagation();

        const preparedText = await prepareShortenSourceText(tweet, tweetText);
        if (!preparedText) {
          return;
        }

        toggleGenerationPanel({
          mode: "shorten",
          wrapperNode: wrapper,
          anchorNode: button,
          sourceText: preparedText
        });
      });

      wrapper.appendChild(button);
      if (mountTarget.mode === "after" && mountTarget.node.parentElement) {
        mountTarget.node.insertAdjacentElement("afterend", wrapper);
      } else if (mountTarget.mode === "after-parent" && mountTarget.node.parentElement) {
        mountTarget.node.parentElement.insertAdjacentElement("afterend", wrapper);
      } else {
        mountTarget.node.appendChild(wrapper);
      }
    });
  }

  function shouldSkipShortenForTweet(tweet) {
    if (!tweet) return true;

    if (isReplyThreadComment(tweet)) {
      return true;
    }

    if (tweet.querySelector(REPLYING_TO_SELECTOR)) {
      return true;
    }

    const articleText = normalizeInlineText(tweet.innerText || tweet.textContent || "");
    if (/replying to|в ответ/i.test(articleText)) {
      return true;
    }

    const threadConnector = tweet.querySelector('div[style*="background-color: rgb(239, 243, 244)"], div[style*="background-color: rgb(47, 51, 54)"]');
    if (threadConnector) {
      return true;
    }

    return false;
  }

  function isReplyThreadComment(tweet) {
    const path = window.location.pathname || "";
    if (!/\/status\/\d+/i.test(path)) {
      return false;
    }

    const tweets = Array.from(document.querySelectorAll(TWEET_SELECTOR));
    const primaryTweet = tweets[0];
    return Boolean(primaryTweet) && tweet !== primaryTweet;
  }

  function injectReplyComposerButtons() {
    document.querySelectorAll(COMPOSER_SELECTOR).forEach((composer) => {
      const context = resolveReplyContext(composer);
      if (!context || context.anchorNode.dataset.piglyReplyRoot === "true") return;
      if (!featureState.replies && !featureState.translate) return;

      const wrapper = document.createElement("div");
      wrapper.className = "pigly-composer-wrapper";

      if (featureState.translate) {
        const translateButton = document.createElement("button");
        translateButton.type = "button";
        translateButton.className = "pigly-composer-trigger pigly-composer-trigger-translate";
        translateButton.title = "Translate typed text to English";
        translateButton.setAttribute("aria-label", "Translate typed text to English");
        translateButton.innerHTML = TRANSLATE_ICON_SVG;
        bindTriggerGuards(translateButton);
        translateButton.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          runInlineTranslate({ button: translateButton, context });
        });
        wrapper.appendChild(translateButton);
      }

      if (featureState.replies) {
        const replyButton = document.createElement("button");
        replyButton.type = "button";
        replyButton.className = "pigly-composer-trigger";
        replyButton.title = "Generate AI reply with Pigly";
        replyButton.setAttribute("aria-label", "Generate AI reply with Pigly");
        replyButton.innerHTML = `<img src="${COMMENT_ICON_SRC}" alt="" class="pigly-trigger-icon">`;
        bindTriggerGuards(replyButton);
        replyButton.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          toggleGenerationPanel({
            mode: "reply",
            wrapperNode: wrapper,
            anchorNode: replyButton,
            sourceText: context.sourceText,
            context
          });
        });
        wrapper.appendChild(replyButton);
      }

      context.anchorNode.dataset.piglyReplyRoot = "true";
      context.anchorNode.setAttribute("data-pigly-reply-root", "true");
      mountReplyWrapper(context, wrapper);
    });
  }

  function bindTriggerGuards(button) {
    ["pointerdown", "mousedown"].forEach((eventName) => {
      button.addEventListener(eventName, (event) => {
        event.preventDefault();
        event.stopPropagation();
      });
    });
  }

  function findShortenMount(tweet, userNameBlock) {
    const timeLink =
      userNameBlock.querySelector('a[href*="/status/"] time')?.closest("a") ||
      userNameBlock.querySelector("time")?.closest("a");
    if (timeLink) {
      return { mode: "after", node: timeLink };
    }

    const handleLink = userNameBlock.querySelector('a[role="link"][href^="/"]');
    if (handleLink) {
      return { mode: "after-parent", node: handleLink };
    }

    const handleNode =
      userNameBlock.querySelector('div[dir="ltr"]') ||
      userNameBlock.querySelector("span");
    if (handleNode) {
      return { mode: "after", node: handleNode };
    }

    const preferredRow =
      userNameBlock.querySelector("div[dir='ltr']")?.parentElement ||
      userNameBlock.firstElementChild ||
      userNameBlock.querySelector("div") ||
      userNameBlock;
    return { mode: "append", node: preferredRow };
  }

  function resolveReplyContext(composer) {
    if (!composer || !composer.isContentEditable || composer.dataset.piglyReplyRoot === "true") {
      return null;
    }

    const richInputContainer = composer.closest(COMPOSER_CONTAINER_SELECTOR);
    const dialog = composer.closest('[role="dialog"]');
    const shell = findReplyShell(composer, richInputContainer, dialog);
    const placeholderText = resolveComposerPlaceholderText(composer, richInputContainer);
    const sourceTweet = findSourceTweet({ composer, shell, dialog });
    const sourceText = sourceTweet ? extractTweetText(sourceTweet) : "";

    if (!isReplyComposer({ dialog, shell, placeholderText, sourceText })) {
      return null;
    }

    const mount = findReplyMount({ composer, dialog, shell, richInputContainer });
    if (!mount || !mount.node) {
      return null;
    }

    return {
      composer,
      dialog,
      shell,
      richInputContainer,
      sourceTweet,
      sourceText,
      mount,
      anchorNode: mount.anchorNode || mount.node
    };
  }

  function findReplyShell(composer, richInputContainer, dialog) {
    if (dialog) {
      return dialog;
    }

    const form = composer.closest("form");
    if (form) {
      return form;
    }

    const candidates = [
      richInputContainer?.parentElement?.parentElement,
      richInputContainer?.parentElement,
      composer.parentElement?.parentElement,
      composer.parentElement
    ].filter(Boolean);

    return candidates.find((node) => {
      const text = normalizeInlineText(node.innerText || node.textContent || "");
      return /reply|ответ/i.test(text);
    }) || richInputContainer?.parentElement || composer.parentElement;
  }

  function resolveComposerPlaceholderText(composer, richInputContainer) {
    const describedBy = composer.getAttribute("aria-describedby");
    if (describedBy) {
      const placeholderNode = document.getElementById(describedBy);
      if (placeholderNode) {
        return normalizeInlineText(placeholderNode.innerText || placeholderNode.textContent || "");
      }
    }

    const placeholder = richInputContainer?.querySelector(".public-DraftEditorPlaceholder-inner");
    return normalizeInlineText(placeholder?.innerText || placeholder?.textContent || "");
  }

  function isReplyComposer({ dialog, shell, placeholderText, sourceText }) {
    if (dialog) return true;
    if (placeholderText && /reply|ответ/i.test(placeholderText)) return true;
    if (shell?.querySelector(REPLYING_TO_SELECTOR)) return true;
    return window.location.pathname.includes("/status/") && !!sourceText;
  }

  function findReplyMount({ composer, dialog, shell, richInputContainer }) {
    const scopes = [
      dialog,
      shell,
      richInputContainer?.parentElement?.parentElement,
      richInputContainer?.parentElement
    ].filter(Boolean);

    for (const scope of scopes) {
      const target = findReplyActionContainer(scope, composer);
      if (target) {
        return { kind: "append", node: target, anchorNode: scope };
      }
    }

    if (richInputContainer && richInputContainer.parentElement) {
      return { kind: "after", node: richInputContainer, anchorNode: richInputContainer };
    }

    return null;
  }

  function findReplyActionContainer(scope, composer) {
    const candidates = scope.querySelectorAll(`${TOOLBAR_SELECTOR}, ${INLINE_ACTIONS_SELECTOR}`);
    for (const candidate of candidates) {
      if (!candidate || candidate.contains(composer)) continue;
      if (candidate.querySelector('[data-testid="tweetButton"], [data-testid="tweetButtonInline"]')) {
        return candidate;
      }
    }
    return null;
  }

  function mountReplyWrapper(context, wrapper) {
    if (context.mount.kind === "after") {
      wrapper.classList.add("pigly-composer-wrapper-below");
      context.mount.node.insertAdjacentElement("afterend", wrapper);
      return;
    }

    context.mount.node.appendChild(wrapper);
  }

  function showInlineComposerNotice(wrapper, message, tone = "neutral") {
    if (!wrapper || !message) return;

    wrapper.querySelectorAll(".pigly-inline-notice").forEach((node) => node.remove());
    const notice = document.createElement("div");
    notice.className = `pigly-inline-notice pigly-inline-notice-${tone}`;
    notice.textContent = message;
    wrapper.appendChild(notice);
    window.setTimeout(() => {
      if (notice.isConnected) {
        notice.remove();
      }
    }, 2200);
  }

  function setComposerButtonLoading(button, isLoading) {
    if (!button) return;
    button.disabled = isLoading;
    button.classList.toggle("is-loading", isLoading);
  }

  function runInlineTranslate({ button, context }) {
    const composer = context?.composer;
    const wrapper = button?.closest(".pigly-composer-wrapper");
    const composerText = readComposerText(composer);

    if (!composerText) {
      showInlineComposerNotice(wrapper, "Type something first.", "error");
      return;
    }

    setComposerButtonLoading(button, true);
    try {
      chrome.runtime.sendMessage({ action: "getSession" }, (sessionRes) => {
        if (chrome.runtime.lastError) {
          showInlineComposerNotice(wrapper, "Reload the page and try again.", "error");
          setComposerButtonLoading(button, false);
          return;
        }
        if (!sessionRes || !sessionRes.authenticated) {
          showInlineComposerNotice(wrapper, "Sign in to Pigly first.", "error");
          setComposerButtonLoading(button, false);
          return;
        }

        chrome.runtime.sendMessage(
          {
            action: "translate",
            payload: {
              text: composerText,
              target_language: "en"
            }
          },
          (response) => {
            if (chrome.runtime.lastError) {
              showInlineComposerNotice(wrapper, "Translation failed.", "error");
              setComposerButtonLoading(button, false);
              return;
            }
            if (!response || !response.ok || !response.data?.translation) {
              showInlineComposerNotice(wrapper, response?.error?.message || "Translation failed.", "error");
              setComposerButtonLoading(button, false);
              return;
            }

            const translatedText = normalizeInlineText(response.data.translation);
            if (!translatedText) {
              showInlineComposerNotice(wrapper, "Translation failed.", "error");
              setComposerButtonLoading(button, false);
              return;
            }

            if (replaceComposerText(composer, translatedText)) {
              showInlineComposerNotice(wrapper, "Translated to English.", "success");
            } else {
              showInlineComposerNotice(wrapper, "Could not update the reply box.", "error");
            }
            setComposerButtonLoading(button, false);
          }
        );
      });
    } catch (_error) {
      showInlineComposerNotice(wrapper, "Translation failed.", "error");
      setComposerButtonLoading(button, false);
    }
  }

  function extractTweetText(tweet) {
    const textNode = tweet.querySelector(TWEET_TEXT_SELECTOR);
    return textNode ? textNode.innerText.trim() : "";
  }

  function findShowMoreControl(tweet) {
    if (!tweet) return null;

    const nodes = tweet.querySelectorAll('div[role="button"], span, a');
    return Array.from(nodes).find((node) => {
      const text = normalizeInlineText(node.textContent || "");
      return /^(show more|more)$/i.test(text);
    }) || null;
  }

  function hasCollapsedShowMore(tweet) {
    return Boolean(findShowMoreControl(tweet));
  }

  async function prepareShortenSourceText(tweet, initialText) {
    if (!tweet) {
      return normalizeInlineText(initialText);
    }

    if (!hasCollapsedShowMore(tweet)) {
      return normalizeInlineText(extractTweetText(tweet) || initialText);
    }

    const showMoreControl = findShowMoreControl(tweet);
    if (!showMoreControl) {
      return normalizeInlineText(extractTweetText(tweet) || initialText);
    }

    try {
      showMoreControl.click();
    } catch (_error) {
      return normalizeInlineText(extractTweetText(tweet) || initialText);
    }

    const initialNormalized = normalizeInlineText(initialText);
    const startedAt = Date.now();

    while (Date.now() - startedAt < 1800) {
      await new Promise((resolve) => setTimeout(resolve, 90));
      const nextText = normalizeInlineText(extractTweetText(tweet));
      if (!hasCollapsedShowMore(tweet) || (nextText && nextText !== initialNormalized)) {
        return nextText || initialNormalized;
      }
    }

    return normalizeInlineText(extractTweetText(tweet) || initialText);
  }

  function findSourceTweet({ composer, shell, dialog, sourceText }) {
    const inlineTweet = composer?.closest(TWEET_SELECTOR);
    if (inlineTweet) {
      return inlineTweet;
    }

    const scopedTweet =
      shell?.querySelector(TWEET_SELECTOR) ||
      dialog?.querySelector(TWEET_SELECTOR) ||
      document.querySelector("main article[data-testid='tweet']");
    if (scopedTweet) {
      return scopedTweet;
    }

    const normalizedSource = normalizeInlineText(sourceText);
    if (!normalizedSource) {
      return null;
    }

    return Array.from(document.querySelectorAll(TWEET_SELECTOR)).find((tweet) => {
      const text = normalizeInlineText(extractTweetText(tweet));
      return text === normalizedSource || text.includes(normalizedSource) || normalizedSource.includes(text);
    }) || null;
  }

  function createPanel(title, mode) {
    const panel = document.createElement("div");
    panel.className = "pigly-panel";
    if (mode === "shorten") {
      panel.classList.add("pigly-panel-shorten");
    }
    const refreshButton = mode === "reply"
      ? `<button type="button" class="pigly-panel-refresh" aria-label="Regenerate replies">${REFRESH_ICON_SVG}</button>`
      : "";
    panel.innerHTML = `
      <div class="pigly-panel-header">
        <div class="pigly-brand">${PIGLY_LOGO_SVG}<span>${title}</span></div>
        ${refreshButton}
        <button type="button" class="pigly-panel-close" aria-label="Close">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"></path></svg>
        </button>
      </div>
      <div class="pigly-panel-content"></div>
    `;

    panel.querySelector(".pigly-panel-close").addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      closePanel();
    });
    panel.addEventListener("click", (event) => event.stopPropagation());
    return panel;
  }

  function bindPanelRefresh(panel, options) {
    const refreshButton = panel.querySelector(".pigly-panel-refresh");
    if (!refreshButton) return;

    refreshButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      runPanelGeneration(panel, { ...options, forceRefresh: true });
    });
  }

  function resolvePanelPlacement(panel, anchorNode) {
    if (!anchorNode) {
      return { horizontal: "left", vertical: "down" };
    }

    const anchorRect = anchorNode.getBoundingClientRect();
    const panelRect = panel.getBoundingClientRect();
    return {
      horizontal: anchorRect.left + panelRect.width > window.innerWidth - 12 ? "right" : "left",
      vertical: anchorRect.bottom + 8 + panelRect.height > window.innerHeight - 12 ? "up" : "down"
    };
  }

  function positionPanel(panel, anchorNode) {
    const isFloating = panel.classList.contains("pigly-panel-floating");
    if (isFloating && anchorNode) {
      const anchorRect = anchorNode.getBoundingClientRect();
      panel.style.top = `${anchorRect.bottom + 8}px`;
      panel.style.left = `${anchorRect.left}px`;
      panel.style.right = "auto";
      panel.style.bottom = "auto";
    }

    const rect = panel.getBoundingClientRect();
    panel.classList.remove("pigly-panel-left", "pigly-panel-up");
    const placement = isFloating
      ? (activePanelPlacement || resolvePanelPlacement(panel, anchorNode))
      : {
          horizontal: rect.right > window.innerWidth - 12 ? "right" : "left",
          vertical: rect.bottom > window.innerHeight - 12 ? "up" : "down"
        };

    if (placement.horizontal === "right") {
      panel.classList.add("pigly-panel-left");
    }
    if (!isFloating && rect.left < 12) {
      panel.classList.remove("pigly-panel-left");
    }
    if (placement.vertical === "up") {
      panel.classList.add("pigly-panel-up");
    }

    if (isFloating && anchorNode) {
      const anchorRect = anchorNode.getBoundingClientRect();
      const nextRect = panel.getBoundingClientRect();
      const preferredLeft = placement.horizontal === "right"
        ? anchorRect.right - nextRect.width
        : anchorRect.left;
      let nextTop = anchorRect.bottom + 8;
      if (placement.vertical === "up") {
        nextTop = anchorRect.top - nextRect.height - 8;
      }
      const nextLeft = Math.min(
        Math.max(12, preferredLeft),
        Math.max(12, window.innerWidth - nextRect.width - 12)
      );
      panel.style.left = `${nextLeft}px`;
      panel.style.top = `${Math.max(12, nextTop)}px`;
      panel.style.right = "auto";
      panel.style.bottom = "auto";
    }
  }

  function refreshActivePanelPosition() {
    if (!activePanel || !activePanelAnchor) return;
    positionPanel(activePanel, activePanelAnchor);
  }

  function handleActivePanelScroll() {
    if (!activePanel || !activePanelAnchor) return;

    const snapshot = getScrollSnapshot();
    if (activePanelScrollSnapshot && getScrollDistance(snapshot, activePanelScrollSnapshot) >= getActivePanelScrollTolerance()) {
      closePanel();
      return;
    }

    positionPanel(activePanel, activePanelAnchor);
  }

  function getScrollSnapshot() {
    const scrollingElement = document.scrollingElement || document.documentElement;
    return {
      x: window.scrollX || scrollingElement.scrollLeft || 0,
      y: window.scrollY || scrollingElement.scrollTop || 0
    };
  }

  function getScrollDistance(nextSnapshot, prevSnapshot) {
    return Math.max(
      Math.abs((nextSnapshot?.x || 0) - (prevSnapshot?.x || 0)),
      Math.abs((nextSnapshot?.y || 0) - (prevSnapshot?.y || 0))
    );
  }

  function getActivePanelScrollTolerance() {
    return activePanelMode === "reply" ? 180 : 72;
  }

  function closePanel() {
    if (!activePanel) return;
    activePanel.remove();
    activePanel = null;
    activePanelAnchor = null;
    activePanelMode = null;
    activePanelPlacement = null;
    activePanelScrollSnapshot = null;
  }

  function getGenerationCacheKey(mode, sourceText, context, payload = {}) {
    const contextText = normalizeInlineText(context?.sourceText || context?.contextText || "");
    return `${mode}::${normalizeInlineText(sourceText)}::${contextText}::${JSON.stringify(payload)}`;
  }

  function renderLoading(container, mode) {
    container.innerHTML = `
      <div class="pigly-loading">
        <div class="pigly-spinner"></div>
        <span>${mode === "shorten" ? "Compressing the post..." : "Generating reply ideas..."}</span>
      </div>
    `;
  }

  function renderError(container, message) {
    container.innerHTML = `
      <div class="pigly-error">${message || "Something went wrong."}</div>
      <button type="button" class="pigly-btn pigly-btn-outline pigly-error-btn">Open Extension</button>
    `;
    container.querySelector(".pigly-error-btn").addEventListener("click", () => {
      alert("Click the Pigly extension icon in your browser toolbar to sign in or adjust settings.");
    });
  }


  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatShortenResultText(text) {
    let value = String(text || "").replace(/\r/g, "").trim();
    if (!value) return "";

    // Normalize spacing but keep existing newlines
    value = value.replace(/[ \t]+\n/g, "\n");
    value = value.replace(/[ \t]{2,}/g, " ");

    // Ensure double newlines for existing single newlines to create distinct paragraphs
    value = value.replace(/\n([^\n])/g, "\n\n$1");
    value = value.replace(/\n{3,}/g, "\n\n");

    // Force newline before list items if they are buried in text
    // Matches "1.", "2.", "•", "-", etc. preceded by a sentence end
    value = value.replace(/([.!?])\s+(\d+[.)]|[\u2022\u25CF\-\*])\s+/g, "$1\n\n$2 ");
    
    // Specifically split handles if they appear as list-like entries
    value = value.replace(/:\s+(@[A-Za-z0-9_])/g, ":\n\n$1");
    value = value.replace(/;\s+(@[A-Za-z0-9_])/g, ";\n\n$1");
    value = value.replace(/([.!?])\s+(@[A-Za-z0-9_])/g, "$1\n\n$2");

    value = value.replace(/\.{3,}\s*$/g, "");
    
    // Final cleanup of extra whitespace
    value = value.replace(/\n\s+\n/g, "\n\n").replace(/\n{3,}/g, "\n\n");
    return value.trim();
  }

  function buildShortenResultMarkup(text) {
    const formatted = formatShortenResultText(text);
    if (!formatted) {
      return `<div class="pigly-result-copy pigly-result-copy-plain"></div>`;
    }

    // Wrap double-newline separated blocks in <p> tags
    const paragraphs = formatted.split(/\n\n+/).filter(Boolean);
    const markup = paragraphs.map(p => {
      let content = escapeHtml(p.trim());
      
      // Highlight handles in the escaped text
      content = content.replace(/(@[A-Za-z0-9_]{2,32})/g, '<span class="pigly-handle">$1</span>');

      // Detect if it's a list item starting with a marker
      if (/^(\d+[.)]|[\u2022\u25CF\-\*])/.test(p.trim())) {
        const markerMatch = content.match(/^(\d+[.)]|[\u2022\u25CF\-\*])\s*/);
        const marker = markerMatch ? markerMatch[0] : "";
        const body = markerMatch ? content.slice(markerMatch[0].length) : content;
        return `<p class="pigly-mb-2"><strong>${marker}</strong> ${body}</p>`;
      }
      return `<p>${content}</p>`;
    }).join("");

    return `<div class="pigly-result-copy pigly-result-copy-plain">${markup}</div>`;
  }

  function renderShortenResult(container, requestData) {
    if (!requestData || !requestData.results || requestData.results.length === 0) {
      renderError(container, "No shortened version was generated.");
      return;
    }
    container.innerHTML = buildShortenResultMarkup(requestData.results[0].content);
  }

  function trimWords(text, wordCount) {
    const words = normalizeInlineText(text).split(" ").filter(Boolean);
    if (!words.length) return "";
    if (words.length <= wordCount) return words.join(" ");
    return `${words.slice(0, wordCount).join(" ")}...`;
  }


  function renderReplyResults(container, requestData, sourceText, context) {
    if (!requestData || !requestData.results || requestData.results.length === 0) {
      renderError(container, "No reply variants were generated.");
      return;
    }

    container.innerHTML = `<div class="pigly-variant-list"></div>`;
    const list = container.querySelector(".pigly-variant-list");
    const styleMeta = requestData.request_data?.result_styles || [];

    requestData.results.forEach((item, index) => {
      const meta = styleMeta.find((entry) => Number(entry.position) === index + 1) || null;
      const row = document.createElement("div");
      row.className = "pigly-variant";
      row.innerHTML = `
        <div class="pigly-variant-head"></div>
        <div class="pigly-variant-text pigly-variant-text-clamped"></div>
        <div class="pigly-variant-actions">
          <button type="button" class="pigly-btn pigly-btn-outline">Copy</button>
          <button type="button" class="pigly-btn">Reply</button>
        </div>
      `;

      const head = row.querySelector(".pigly-variant-head");
      if (meta?.style_label) {
        head.innerHTML = `<span class="pigly-variant-style">${meta.style_label}</span>`;
      } else {
        head.remove();
      }
      row.querySelector(".pigly-variant-text").textContent = item.content;

      const buttons = row.querySelectorAll(".pigly-btn");
      buttons[0].addEventListener("click", (event) => {
        const button = event.currentTarget;
        navigator.clipboard.writeText(item.content);
        button.textContent = "Copied";
        setTimeout(() => {
          button.textContent = "Copy";
        }, 1800);
      });
      buttons[1].addEventListener("click", () => {
        openNativeReply({ context, sourceText, replyText: item.content });
        closePanel();
      });

      list.appendChild(row);
    });
  }

  function openNativeReply({ context, sourceText, replyText }) {
    if (injectTextIntoComposer(replyText, context?.composer)) {
      return;
    }

    const replyHostTweet =
      context?.sourceTweet ||
      findSourceTweet({ sourceText }) ||
      document.querySelector("main article[data-testid='tweet']");
    const replyButton = replyHostTweet ? replyHostTweet.querySelector('[data-testid="reply"]') : null;
    if (replyButton) {
      replyButton.click();
      waitForComposerAndInsert(replyText, context?.composer);
      return;
    }

    injectTextIntoComposer(replyText);
  }

  function waitForComposerAndInsert(text, previousComposer) {
    const startedAt = Date.now();
    const tryInsert = () => {
      const composer = getPreferredComposer(previousComposer);
      if (injectTextIntoComposer(text, composer)) {
        return;
      }

      if (Date.now() - startedAt < 3000) {
        requestAnimationFrame(tryInsert);
        return;
      }

      navigator.clipboard.writeText(text);
      alert("Pigly copied the reply because the reply field was not found.");
    };

    setTimeout(tryInsert, 250);
  }

  function getPreferredComposer(preferredComposer) {
    if (preferredComposer && preferredComposer.isConnected) {
      return preferredComposer;
    }

    if (document.activeElement?.matches?.(COMPOSER_SELECTOR)) {
      return document.activeElement;
    }

    return document.querySelector(COMPOSER_SELECTOR);
  }

  function injectTextIntoComposer(text, preferredComposer) {
    const composer = getPreferredComposer(preferredComposer);
    if (!composer) {
      navigator.clipboard.writeText(text);
      alert("Pigly copied the reply because the reply field was not found.");
      return false;
    }

    composer.focus();
    selectComposerContents(composer);

    let inserted = false;
    try {
      inserted = document.execCommand("insertText", false, text);
    } catch (_error) {
      inserted = false;
    }

    if (!inserted || readComposerText(composer) !== normalizeInlineText(text)) {
      inserted = replaceComposerText(composer, text);
    }

    return inserted;
  }

  function selectComposerContents(composer) {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(composer);
    range.collapse(false);
    selection.removeAllRanges();
    selection.addRange(range);
  }

  function replaceComposerText(composer, text) {
    try {
      composer.focus();
      dispatchComposerInputEvent(composer, "beforeinput", text);
      composer.textContent = text;
      selectComposerContents(composer);
      dispatchComposerInputEvent(composer, "input", text);
      composer.dispatchEvent(new Event("change", { bubbles: true }));
      return readComposerText(composer) === normalizeInlineText(text);
    } catch (_error) {
      return false;
    }
  }

  function dispatchComposerInputEvent(composer, type, text) {
    try {
      composer.dispatchEvent(new InputEvent(type, {
        bubbles: true,
        cancelable: type === "beforeinput",
        data: text,
        inputType: "insertText"
      }));
    } catch (_error) {
      composer.dispatchEvent(new Event(type, { bubbles: true, cancelable: type === "beforeinput" }));
    }
  }

  function readComposerText(composer) {
    return normalizeInlineText(composer.innerText || composer.textContent || "");
  }

  function normalizeInlineText(text) {
    return String(text || "").replace(/\s+/g, " ").trim();
  }

  function normalizeShortenerTriggerLength(value) {
    const parsed = Number.parseInt(value, 10);
    if (!Number.isFinite(parsed)) return DEFAULT_SHORTENER_TRIGGER_LENGTH;
    return Math.max(1, Math.min(10000, parsed));
  }

  function resolveShortenerTriggerLength(defaults) {
    return normalizeShortenerTriggerLength(defaults?.shorten_trigger_length || DEFAULT_SHORTENER_TRIGGER_LENGTH);
  }

  function shouldShowShortenButton(tweet, sourceText) {
    if (hasCollapsedShowMore(tweet)) {
      return true;
    }
    return normalizeInlineText(sourceText).length >= shortenerTriggerLength;
  }

  function getShortenTargetLength(sourceText) {
    const normalized = normalizeInlineText(sourceText);
    const sourceLength = normalized.length;
    if (!sourceLength) {
      return 180;
    }

    const estimated = Math.round(sourceLength * 0.72);
    const minimumReduction = Math.max(18, Math.round(sourceLength * 0.1));
    const maxTarget = Math.max(80, sourceLength - minimumReduction);
    return Math.max(120, Math.min(380, maxTarget, estimated || maxTarget));
  }

  function runPanelGeneration(panel, { contentBox, mode, sourceText, context, forceRefresh = false }) {
    if (!panel || panel.dataset.loading === "true") return;

    panel.dataset.loading = "true";
    const refreshButton = panel.querySelector(".pigly-panel-refresh");
    if (refreshButton) {
      refreshButton.disabled = true;
      refreshButton.classList.add("is-loading");
    }

    renderLoading(contentBox, mode);

    if (!sourceText) {
      renderError(contentBox, mode === "shorten" ? "The post text was not found." : "The source post for this reply was not found.");
      finishPanelGeneration(panel);
      return;
    }

    requestSessionAndGenerate(contentBox, mode, sourceText, context, panel, { forceRefresh });
  }

  function finishPanelGeneration(panel) {
    if (!panel) return;
    panel.dataset.loading = "false";
    const refreshButton = panel.querySelector(".pigly-panel-refresh");
    if (refreshButton) {
      refreshButton.disabled = false;
      refreshButton.classList.remove("is-loading");
    }
  }

  function toggleGenerationPanel({ mode, wrapperNode, anchorNode, sourceText, context }) {
    const resolvedAnchor = anchorNode || wrapperNode;
    if (activePanel && activePanelAnchor === resolvedAnchor) {
      closePanel();
      return;
    }

    closePanel();

    const panel = createPanel(mode === "shorten" ? "Shorten" : "AI Reply", mode);
    panel.classList.add("pigly-panel-floating");
    document.body.appendChild(panel);
    activePanel = panel;
    activePanelAnchor = resolvedAnchor;
    activePanelMode = mode;
    activePanelPlacement = null;
    activePanelScrollSnapshot = getScrollSnapshot();
    const contentBox = panel.querySelector(".pigly-panel-content");
    bindPanelRefresh(panel, { contentBox, mode, sourceText, context });

    requestAnimationFrame(() => {
      activePanelPlacement = resolvePanelPlacement(panel, resolvedAnchor);
      panel.classList.add("show");
      positionPanel(panel, resolvedAnchor);
    });
    runPanelGeneration(panel, { contentBox, mode, sourceText, context });
  }

  function requestSessionAndGenerate(contentBox, mode, sourceText, context, panel, options = {}) {
    pruneGenerationCache();
    const forceRefresh = options.forceRefresh === true;
    const useCache = true;

    try {
      chrome.runtime.sendMessage({ action: "getSession" }, (sessionRes) => {
        if (!sessionRes || !sessionRes.authenticated) {
          renderError(contentBox, "Please sign in to Pigly first.");
          finishPanelGeneration(panel);
          return;
        }

        const payload =
          mode === "shorten"
            ? {
                text: sourceText,
                language: sessionRes.user?.defaults?.translate_to_language || "",
                variant_count: 1,
                target_length: getShortenTargetLength(sourceText)
              }
            : {
                text: sourceText,
                context: "",
                language: sessionRes.user?.defaults?.translate_to_language || "",
                variant_count: sessionRes.user?.defaults?.variant_count || 3
              };

        const cacheKey = getGenerationCacheKey(mode, sourceText, context, payload);

        if (useCache && !forceRefresh) {
          const cachedRequest = getCachedGeneration(cacheKey);
          if (cachedRequest) {
            if (mode === "shorten") {
              renderShortenResult(contentBox, cachedRequest);
            } else {
              renderReplyResults(contentBox, cachedRequest, sourceText, context);
            }
            finishPanelGeneration(panel);
            return;
          }
        }

        chrome.runtime.sendMessage({ action: mode, payload }, (response) => {
          if (chrome.runtime.lastError) {
            renderError(contentBox, "Extension connection was lost. Reload the page.");
            finishPanelGeneration(panel);
            return;
          }
          if (!response || !response.ok) {
            renderError(contentBox, response?.error?.message || "Generation failed.");
            finishPanelGeneration(panel);
            return;
          }

          if (useCache) {
            setCachedGeneration(cacheKey, response.data.request);
          }

          if (mode === "shorten") {
            renderShortenResult(contentBox, response.data.request);
          } else {
            renderReplyResults(contentBox, response.data.request, sourceText, context);
          }
          finishPanelGeneration(panel);
        });
      });
    } catch (_error) {
      renderError(contentBox, "Pigly could not contact the extension.");
      finishPanelGeneration(panel);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
