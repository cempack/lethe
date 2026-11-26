// Lethe for GNOME Shell: the desktop of a Lethe session.
//
//  - a dock along the bottom, like macOS: favourites, then running apps, then the app grid;
//  - a quieter top bar: the Lethe mark and the active app's name on the left, the clock on the right;
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
import * as AppFavorites from 'resource:///org/gnome/shell/ui/appFavorites.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const ICON = 46;
const CLIP_LABEL = 'LETHECLIP';
const MAX_CLIP = 32 * 1024 * 1024;

class Dock {
    constructor() {
        this._apps = Shell.AppSystem.get_default();
        this._favs = AppFavorites.getAppFavorites();

        this.actor = new St.Widget({layout_manager: new Clutter.BinLayout(), reactive: false, name: 'letheDockArea'});
        this._box = new St.BoxLayout({style_class: 'lethe-dock', reactive: true,
                                      x_expand: true, y_expand: true,
                                      x_align: Clutter.ActorAlign.CENTER, y_align: Clutter.ActorAlign.END});
        this.actor.add_child(this._box);
        this._label = new St.Label({style_class: 'lethe-dock-label', visible: false});
        Main.layoutManager.addTopChrome(this._label);
        // Windows maximise above the dock, as on a Mac with the dock always shown.
        Main.layoutManager.addChrome(this.actor, {affectsStruts: true, trackFullscreen: true});

        this._favs.connectObject('changed', () => this._rebuild(), this);
        this._apps.connectObject('app-state-changed', () => this._rebuild(), 'installed-changed', () => this._rebuild(), this);
        Main.layoutManager.connectObject('monitors-changed', () => this._place(), this);
        Main.overview.connectObject('showing', () => this.actor.hide(), 'hidden', () => this.actor.show(), this);
        this._rebuild();
    }

    _rebuild() {
        this._box.destroy_all_children();
        const favs = this._favs.getFavorites();
        const running = this._apps.get_running().filter(a => !favs.includes(a));
        for (const app of favs)
            this._box.add_child(this._item(app));
        if (running.length) {
            this._box.add_child(new St.Widget({style_class: 'lethe-dock-sep', y_expand: true}));
            for (const app of running)
                this._box.add_child(this._item(app));
        }
        this._box.add_child(new St.Widget({style_class: 'lethe-dock-sep', y_expand: true}));
        const grid = this._button(new St.Icon({icon_name: 'view-app-grid-symbolic', icon_size: ICON - 18,
                                              style_class: 'lethe-dock-grid'}), 'Applications', false);
        grid.connect('clicked', () => Main.overview.visible ? Main.overview.hide() : Main.overview.showApps());
        this._box.add_child(grid);
        this._place();
    }

    _button(icon, name, running) {
        const column = new St.BoxLayout({vertical: true, x_align: Clutter.ActorAlign.CENTER});
        icon.set_pivot_point(0.5, 1);
        column.add_child(icon);
        column.add_child(new St.Widget({style_class: 'lethe-dock-dot', opacity: running ? 255 : 0,
                                        x_align: Clutter.ActorAlign.CENTER}));
        const button = new St.Button({style_class: 'lethe-dock-item', child: column, track_hover: true});
        button.connect('notify::hover', () => {
            icon.ease({scale_x: button.hover ? 1.14 : 1, scale_y: button.hover ? 1.14 : 1, duration: 140,
                       mode: Clutter.AnimationMode.EASE_OUT_QUAD});
            this._tooltip(button, button.hover ? name : null);
        });
        return button;
    }

    _item(app) {
        const button = this._button(app.create_icon_texture(ICON), app.get_name(),
                                     app.get_state() !== Shell.AppState.STOPPED);
        button.connect('clicked', () => {
            this._tooltip(button, null);
            Main.overview.hide();
            app.activate();
        });
        return button;
    }

    _tooltip(button, text) {
        if (!text)
            return this._label.hide();
        this._label.text = text;
        this._label.show();
        const [x, y] = button.get_transformed_position();
        const [, w] = this._label.get_preferred_width(-1);
        const [, h] = this._label.get_preferred_height(-1);
        this._label.set_position(Math.round(x + button.width / 2 - w / 2), Math.round(y - h - 10));
    }

    _place() {
        const m = Main.layoutManager.primaryMonitor;
        if (!m)
            return;
        const [, h] = this._box.get_preferred_height(-1);
        const height = h + 10;
        this.actor.set_position(m.x, m.y + m.height - height);
        this.actor.set_size(m.width, height);
    }

    destroy() {
        this._favs.disconnectObject(this);
        this._apps.disconnectObject(this);
        Main.layoutManager.disconnectObject(this);
        Main.overview.disconnectObject(this);
        this._label.destroy();
        this.actor.destroy();
    }
}

class TopBar {
    constructor(dir) {
        const panel = Main.panel;
        this._activities = panel.statusArea.activities;
        this._activities?.container.hide();

        this._left = new St.Button({style_class: 'panel-button lethe-mark', track_hover: true});
        const row = new St.BoxLayout({y_align: Clutter.ActorAlign.CENTER});
        row.add_child(new St.Icon({gicon: Gio.icon_new_for_string(dir.get_child('mark.svg').get_path()),
                                   icon_size: 15, style_class: 'lethe-mark-icon'}));
        this._left.set_child(row);
        this._left.connect('clicked', () => Main.overview.visible ? Main.overview.hide() : Main.overview.showApps());
        this._name = new St.Label({style_class: 'panel-button lethe-app-name', y_align: Clutter.ActorAlign.CENTER});
        panel._leftBox.insert_child_at_index(this._left, 0);
        panel._leftBox.insert_child_at_index(this._name, 1);

        // The clock goes to the right-hand end, where a Mac has it.
        this._clock = panel.statusArea.dateMenu?.container;
        if (this._clock) {
            this._clockParent = this._clock.get_parent();
            this._clockIndex = this._clockParent.get_children().indexOf(this._clock);
            this._clockParent.remove_child(this._clock);
            panel._rightBox.add_child(this._clock);
        }

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
        if (this._clock) {
            this._clock.get_parent()?.remove_child(this._clock);
            this._clockParent.insert_child_at_index(this._clock, this._clockIndex);
        }
        this._left.destroy();
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
        this._dock = new Dock();
        this._bar = new TopBar(this.dir);
        this._clipboard = new Clipboard();
        // Lethe used the Looking Glass console once, to load this. Close it for the rest of the session.
        new Gio.Settings({schema_id: 'org.gnome.shell'}).set_boolean('development-tools', false);
    }

    disable() {
        this._clipboard?.destroy();
        this._bar?.destroy();
        this._dock?.destroy();
        this._clipboard = this._bar = this._dock = null;
        Main.layoutManager.uiGroup.remove_style_class_name('lethe');
    }
}
