// IRCC Tracker — Service Worker for Web Push notifications

self.addEventListener("push", event => {
    let data = {};
    try { data = event.data ? event.data.json() : {}; } catch (e) {}

    const title = data.title || "IRCC Tracker";
    const options = {
        body: data.body || "An application has been updated.",
        tag: data.app_number || "ircc-update",
        renotify: true,
        data: { url: data.url || "/applications" },
    };
    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", event => {
    event.notification.close();
    const targetUrl = (event.notification.data && event.notification.data.url) || "/applications";
    event.waitUntil(
        clients.matchAll({ type: "window", includeUncontrolled: true }).then(list => {
            for (const c of list) {
                if ("focus" in c) return c.focus();
            }
            return clients.openWindow(targetUrl);
        })
    );
});
