// Lethe for GNOME Shell: the desktop of a Lethe session.
//
//  - a dock along the bottom: GNOME's own dash, kept on the desktop instead of hidden in the overview;
//  - the Lethe mark and the active app's name at the start of the top bar;
//  - the receiving end of Lethe's one-way clipboard. Lethe puts what you copied on your computer
//    on a read-only disc labelled LETHECLIP; this mounts it, hands the text or image to the
//    clipboard, and lets the disc go. Nothing is ever sent the other way.
//
// Loaded by Lethe right after login and gone when the session ends, like everything in Tails.
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Dash} from 'resource:///org/gnome/shell/ui/dash.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const CLIP_LABEL = 'LETHECLIP';
const MAX_CLIP = 32 * 1024 * 1024;

// The dock is GNOME's own dash (the one in the overview), shown on the desktop as well. Everything
// in it is GNOME's: dragging to reorder, right-click menus, running dots, labels, keyboard focus.
class Dock {
    constructor(scale) {
        this._icon = scale >= 1.2 ? 64 : 48;
        this._dash = new Dash();
        this._dash.add_style_class_name('lethe-dock');
        this._dash.showAppsButton.connectObject('notify::checked', button => {
            if (button.checked)
                Main.overview.showApps();
            else if (Main.overview.visible)
                Main.overview.hide();
        }, this);

        this.actor = new St.Bin({child: this._dash, x_align: Clutter.ActorAlign.CENTER, y_align: Clutter.ActorAlign.END});
        // Windows maximise above the dock, and it steps aside for full-screen apps.
        Main.layoutManager.addChrome(this.actor, {affectsStruts: true, trackFullscreen: true});
        Main.layoutManager.connectObject('monitors-changed', () => this._place(), this);
        Main.overview.connectObject(
            'showing', () => this.actor.hide(),
            'hidden', () => {
                this._dash.showAppsButton.checked = false;
                this.actor.show();
            }, this);
        this._dash.connectObject('notify::height', () => this._place(), this);
        this._place();
    }

    _place() {
        const m = Main.layoutManager.primaryMonitor;
        if (!m)
            return;
        // The dash picks the largest of its icon sizes that fits the height it is given.
        this._dash.setMaxSize(Math.round(m.width * 0.92), this._icon + 56);
        const [, height] = this._dash.get_preferred_height(-1);
        this.actor.set_position(m.x, m.y + m.height - height);
        this.actor.set_size(m.width, height);
    }

    destroy() {
        Main.layoutManager.disconnectObject(this);
        Main.overview.disconnectObject(this);
        this.actor.destroy();
    }
}

// The top bar stays GNOME's. Tails has no overview button, so the Lethe mark takes that place
// (it opens the apps), followed by the name of the app in front.
class TopBar {
    constructor(dir) {
        const panel = Main.panel;
        this._activities = panel.statusArea.activities;
        this._activities?.container.hide();

        this._mark = new St.Button({style_class: 'panel-button lethe-mark', track_hover: true, can_focus: true,
                                    accessible_name: 'Apps'});
        this._mark.set_child(new St.Icon({gicon: Gio.icon_new_for_string(dir.get_child('mark.svg').get_path()),
                                          style_class: 'system-status-icon'}));
        this._mark.connect('clicked', () => Main.overview.visible ? Main.overview.hide() : Main.overview.showApps());
        this._name = new St.Label({style_class: 'lethe-app-name', y_align: Clutter.ActorAlign.CENTER});
        panel._leftBox.insert_child_at_index(this._mark, 0);
        panel._leftBox.insert_child_at_index(this._name, 1);

        this._tracker = Shell.WindowTracker.get_default();
        this._tracker.connectObject('notify::focus-app', () => this._update(), this);
        this._update();
    }

    _update() {
        const app = this._tracker.focus_app;
        this._name.text = app ? app.get_name() : 'Tails';
    }

    destroy() {
        this._tracker.disconnectObject(this);
        this._mark.destroy();
        this._name.destroy();
        this._activities?.container.show();
    }
}

class Clipboard {
    constructor() {
        this._monitor = Gio.VolumeMonitor.get();
        this._seen = null;
        // A new disc in the same drive can arrive as a new volume or as a change to the old one.
        this._monitor.connectObject('volume-added', (_m, volume) => this._volume(volume),
                                    'volume-changed', (_m, volume) => this._volume(volume), this);
        for (const volume of this._monitor.get_volumes())
            this._volume(volume);
    }

    _volume(volume) {
        // Every clipboard disc has its own label (LETHECLIP-<n>): read each one once.
        const label = volume.get_identifier('label') || volume.get_name() || '';
        if (!label.startsWith(CLIP_LABEL) || label === this._seen || volume.get_mount())
            return;
        this._seen = label;
        volume.mount(Gio.MountMountFlags.NONE, null, null, (_v, result) => {
            let mount;
            try {
                volume.mount_finish(result);
                mount = volume.get_mount();
                this._read(mount.get_root());
            } catch (e) {
                console.warn(`Lethe clipboard: ${e.message}`);
            }
            mount?.unmount_with_operation(Gio.MountUnmountFlags.FORCE, null, null, (m, r) => {
                try {
                    m.unmount_with_operation_finish(r);
                } catch (_e) {}
            });
        });
    }

    _read(root) {
        const [, mimeBytes] = root.get_child('mime.txt').load_contents(null);
        const mime = new TextDecoder().decode(mimeBytes).trim();
        const data = root.get_child('data.bin');
        if (data.query_info('standard::size', 0, null).get_size() > MAX_CLIP)
            return;
        const [, bytes] = data.load_contents(null);
        const clipboard = St.Clipboard.get_default();
        if (mime.startsWith('text/'))
            clipboard.set_text(St.ClipboardType.CLIPBOARD, new TextDecoder().decode(bytes));
        else if (/^image\/(png|jpeg|gif|webp)$/.test(mime))
            clipboard.set_content(St.ClipboardType.CLIPBOARD, mime, new GLib.Bytes(bytes));
    }

    destroy() {
        this._monitor.disconnectObject(this);
    }
}

export default class LetheExtension extends Extension {
    enable() {
        Main.layoutManager.uiGroup.add_style_class_name('lethe');
        const scale = new Gio.Settings({schema_id: 'org.gnome.desktop.interface'}).get_double('text-scaling-factor');
        this._dock = new Dock(scale);
        this._bar = new TopBar(this.dir);
        this._clipboard = new Clipboard();
        this._refreshAppGrid();
        // Lethe used the Looking Glass console once, to load this. Close it for the rest of the session.
        new Gio.Settings({schema_id: 'org.gnome.shell'}).set_boolean('development-tools', false);
    }

    // setup.sh gave some launchers a Lethe icon. The dock picks that up by itself; the app grid keeps
    // the icons it drew at login, so the ones whose launcher changed are dropped and drawn again.
    _refreshAppGrid() {
        try {
            const grid = Main.overview._overview.controls.appDisplay;
            const apps = Shell.AppSystem.get_default();
            for (const [id, icon] of [...grid._items]) {
                if (icon.app && icon.app !== apps.lookup_app(id)) {
                    grid._removeItem(icon);
                    icon.destroy();
                }
            }
            grid._redisplay();
        } catch (e) {
            console.warn(`Lethe app grid: ${e.message}`);
        }
    }

    disable() {
        this._clipboard?.destroy();
        this._bar?.destroy();
        this._dock?.destroy();
        this._clipboard = this._bar = this._dock = null;
        Main.layoutManager.uiGroup.remove_style_class_name('lethe');
    }
}
