/*
 * App-level JavaScript for scoped management plane.
 * Configures HTMX, CSRF, Clerk, and global alert system.
 */

document.addEventListener("DOMContentLoaded", function () {
    // Include Django CSRF token in all HTMX requests
    document.body.addEventListener("htmx:configRequest", function (event) {
        var cookie = document.cookie.match(/csrftoken=([^;]+)/);
        if (cookie) {
            event.detail.headers["X-CSRFToken"] = cookie[1];
        }
    });
});


/**
 * Global alert system — dispatch from anywhere via custom event.
 *
 * Usage:
 *   showAlert("Copied to clipboard", "success");
 *   showAlert("Something went wrong", "error");
 */
function showAlert(message, type) {
    window.dispatchEvent(new CustomEvent("alert", {
        detail: { message: message, type: type || "info" },
    }));
}

function alertManager() {
    return {
        alerts: [],
        _counter: 0,
        show: function (detail) {
            var id = ++this._counter;
            this.alerts.push({
                id: id,
                message: detail.message,
                type: detail.type || "info",
                visible: true,
            });
            var self = this;
            setTimeout(function () { self.dismiss(id); }, 3000);
        },
        dismiss: function (id) {
            var alert = this.alerts.find(function (a) { return a.id === id; });
            if (alert) alert.visible = false;
            var self = this;
            setTimeout(function () {
                self.alerts = self.alerts.filter(function (a) { return a.id !== id; });
            }, 300);
        },
    };
}


/**
 * Global confirmation modal — replaces browser confirm() dialogs.
 *
 * Usage in templates:
 *   <form x-data @submit.prevent="confirmAction({
 *       title: 'Revoke key?',
 *       message: 'This cannot be undone.',
 *       action: 'Revoke',
 *       destructive: true,
 *       form: $el
 *   })">
 */
function confirmModal() {
    return {
        visible: false,
        title: "",
        message: "",
        action: "",
        destructive: false,
        _form: null,
        open: function (detail) {
            this.title = detail.title || "Are you sure?";
            this.message = detail.message || "";
            this.action = detail.action || "Confirm";
            this.destructive = detail.destructive || false;
            this._form = detail.form || null;
            this.visible = true;
        },
        cancel: function () {
            this.visible = false;
            this._form = null;
        },
        proceed: function () {
            this.visible = false;
            if (this._form) {
                this._form.submit();
            }
        },
    };
}

function confirmAction(detail) {
    window.dispatchEvent(new CustomEvent("confirm", { detail: detail }));
}


/**
 * Copy text to clipboard and show a global alert.
 */
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(function () {
        showAlert("Copied to clipboard", "success");
    });
}


/**
 * Run a callback once Clerk JS has loaded.
 * No-op if the Clerk script tag is not on the page.
 */
function onClerkReady(callback) {
    var attempts = 0;
    function check() {
        if (window.Clerk && window.Clerk.loaded) {
            callback(window.Clerk);
        } else if (window.Clerk) {
            window.Clerk.load().then(function () {
                callback(window.Clerk);
            });
        } else if (attempts < 100) {
            attempts++;
            setTimeout(check, 50);
        }
    }
    // Wait for DOM to finish parsing so the Clerk script tag is present
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", check);
    } else {
        check();
    }
}


/**
 * Sync Clerk session token to a __session cookie on our domain.
 */
function syncClerkSession(clerk) {
    if (!clerk.session) {
        document.cookie = "__session=; path=/; max-age=0";
        return Promise.resolve();
    }
    return clerk.session.getToken().then(function (token) {
        if (token) {
            document.cookie = "__session=" + token + "; path=/; SameSite=Lax";
        } else {
            document.cookie = "__session=; path=/; max-age=0";
        }
    });
}


// Keep session cookie in sync and mount UserButton
onClerkReady(function (clerk) {
    syncClerkSession(clerk).then(function () {
        // After cookie sync, reload the page once so the server-rendered
        // navbar reflects auth state (shows Dashboard button vs Sign in).
        // Only reload if auth state changed since server render.
        var serverAuthed = !!document.querySelector("[data-clerk-authed]");
        if (clerk.user && !serverAuthed) {
            window.location.reload();
        }
    });
    clerk.addListener(function () {
        syncClerkSession(clerk);
    });

    var el = document.getElementById("clerk-user-button");
    if (el) {
        clerk.mountUserButton(el, {
            afterSignOutUrl: "/",
        });
    }
});
