/*
 * Public website interaction helpers.
 * Configures HTMX, CSRF, and global alerts.
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
