// Lethe for GNOME Shell: the desktop of a Lethe session.
//
//  - a dock along the bottom: GNOME's own dash, kept on the desktop; it slides away under maximised windows;
//  - the Lethe mark and the active app's name at the start of the top bar;
//  - the receiving end of Lethe's one-way clipboard. Lethe puts what you copied on your computer
//    on a read-only disc labelled LETHECLIP; this mounts it, hands the text or image to the
//    clipboard, and lets the disc go. Nothing is ever sent the other way.
//
// Loaded by Lethe right after login and gone when the session ends, like everything in Tails.
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GObject from 'gi://GObject';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Dash} from 'resource:///org/gnome/shell/ui/dash.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const CLIP_LABEL = 'LETHECLIP';
const MAX_CLIP = 32 * 1024 * 1024;

// The dock is GNOME's own dash (the one in the overview), shown on the desktop as well. Everything
// in it is GNOME's: dragging to reorder, right-click menus, running marks, labels, keyboard focus.
// One thing differs: its icons have one fixed size, matched to the screen's scale (the stock dash
// only knows 48 and 64).
const LetheDash = GObject.registerClass(
class LetheDash extends Dash {
    _init(size) {
        this._size = size;
        super._init();
        this.iconSize = size;
    }

    // A right-click menu is open on one of the icons (the dock must not slide away under it).
    _itemMenuStateChanged(item, opened) {
        super._itemMenuStateChanged(item, opened);
        this.menuOpen = opened;
        this.onMenu?.();
    }

    resize(size) {
        if (size !== this._size) {
            this._size = size;
            this._adjustIconSize();
        }
    }

    _adjustIconSize() {
        const icons = this._box.get_children()
            .filter(actor => actor.child?._delegate?.icon && !actor.animatingOut)
            .map(actor => actor.child._delegate.icon);
        icons.push(this._showAppsIcon.icon);
        for (const icon of icons)
            icon.setIconSize(this._size);
        if (this._separator)
            this._separator.height = this._size;
        if (this.iconSize !== this._size) {
            this.iconSize = this._size;
            this.emit('icon-size-changed');
        }
    }
});

// Where the dock is and when. It floats over the desktop and takes no room from windows. When a
// window on this workspace reaches into its place it slides away, and comes back while the pointer
// rests on the bottom edge of the screen, or on the dock itself.
class Dock {
    constructor(scale) {
        this._scale = scale;
        this._shown = true;
        this._timers = new Map();
        this._dash = new LetheDash(this._size());
        this._dash.add_style_class_name('lethe-dock');
        this._dash.onMenu = () => this._soon('sync', 100);
        this._dash.showAppsButton.connectObject('notify::checked', button => {
            if (button.checked)
                Main.overview.showApps();
            else if (Main.overview.visible)
                Main.overview.hide();
        }, this);

        this.actor = new St.Bin({child: this._dash, reactive: true, track_hover: true});
        this._edge = new St.Widget({reactive: true, track_hover: true});
        for (const actor of [this.actor, this._edge])
            Main.layoutManager.addChrome(actor, {affectsStruts: false, trackFullscreen: true});
        this.actor.connect('notify::hover', () => this._soon('sync', this.actor.hover ? 0 : 350));
        // Resting on the edge calls the dock; merely passing over it does not.
        this._edge.connect('notify::hover', () => this._soon('sync', this._edge.hover ? 150 : 350));

        const later = () => this._soon('sync', 120);
        global.window_manager.connectObject('size-changed', later, 'minimize', later, 'unminimize', later,
            'map', later, 'destroy', later, 'switch-workspace', later, this);
        global.display.connectObject('restacked', later, 'grab-op-end', later, this);
        Main.layoutManager.connectObject('monitors-changed', () => this._place(), this);
        Main.overview.connectObject('showing', () => this._sync(), 'hidden', () => {
            this._dash.showAppsButton.checked = false;
            this._sync();
        }, this);
        this._dash.connectObject('notify::height', () => this._place(), 'notify::width', () => this._place(), this);
        this._place();
        // It always shows itself for a moment when the session starts, whatever is on screen.
        this._hello = true;
        this._soon('hello', 4000, () => {
            this._hello = false;
            this._sync();
        });
    }

    _soon(name, ms, run = () => this._sync()) {
        if (this._timers.has(name))
            GLib.source_remove(this._timers.get(name));
        this._timers.set(name, GLib.timeout_add(GLib.PRIORITY_DEFAULT, ms, () => {
            this._timers.delete(name);
            run();
            return GLib.SOURCE_REMOVE;
        }));
    }

    // 48 px at the screen's scale, less when the session window is narrow: the dock never takes
    // more than its share of a small screen.
    _size() {
        const m = Main.layoutManager.primaryMonitor;
        const fit = m ? m.width / 20 : Infinity;
        return Math.round(Math.max(32, Math.min(48 * this._scale, fit)) / 2) * 2;
    }

    _place() {
        const m = Main.layoutManager.primaryMonitor;
        if (!m)
            return;
        this._dash.resize(this._size());
        const [, width] = this._dash.get_preferred_width(-1);
        const [, height] = this._dash.get_preferred_height(-1);
        this.actor.set_position(m.x + Math.floor((m.width - width) / 2), m.y + m.height - height);
        this.actor.set_size(width, height);
        this._edge.set_position(m.x, m.y + m.height - 2);
        this._edge.set_size(m.width, 2);
        if (!this._shown)
            this.actor.translation_y = height;
    }

    // A window that reaches into the dock's place (a maximised one, or simply a tall one) would
    // have its lower edge, often its buttons, under the dock.
    _covered() {
        const workspace = global.workspace_manager.get_active_workspace();
        const primary = Main.layoutManager.primaryIndex;
        const [left, top] = [this.actor.x, this.actor.y];
        const [right, bottom] = [left + this.actor.width, top + this.actor.height];
        return global.get_window_actors().some(actor => {
            const w = actor.meta_window;
            if (!w || w.minimized || w.get_window_type() !== Meta.WindowType.NORMAL ||
                w.get_monitor() !== primary || !w.located_on_workspace(workspace))
                return false;
            const f = w.get_frame_rect();
            return f.x < right && f.x + f.width > left && f.y < bottom && f.y + f.height > top;
        });
    }

    _sync() {
        if (Main.overview.visible)            // the overview has the dash of its own
            return this._slide(false, 0);
        const wanted = this.actor.hover || this._edge.hover || this._dash.menuOpen;
        this._slide(this._hello || wanted || !this._covered(), 180);
    }

    _slide(shown, ms) {
        const actor = this.actor;
        if (shown === this._shown && actor.visible === shown)
            return;
        this._shown = shown;
        if (shown)
            actor.show();
        actor.save_easing_state();
        actor.set_easing_mode(Clutter.AnimationMode.EASE_OUT_CUBIC);
        actor.set_easing_duration(actor.mapped ? ms : 0);
        actor.translation_y = shown ? 0 : actor.height;
        actor.restore_easing_state();
        if (!shown)
            this._soon('hide', ms + 30, () => !this._shown && actor.hide());
        else if (this._timers.has('hide'))
            this._soon('hide', 0, () => {});
    }

    destroy() {
        for (const id of this._timers.values())
            GLib.source_remove(id);
        global.window_manager.disconnectObject(this);
        global.display.disconnectObject(this);
        Main.layoutManager.disconnectObject(this);
        Main.overview.disconnectObject(this);
        this._edge.destroy();
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

        // Two indicators have no job in a Lethe session: the keyboard layout (Lethe translates your
        // own layout as you type) and the accessibility menu, which stays available in Settings.
        this._hidden = ['keyboard', 'a11y'].map(role => panel.statusArea[role]?.container).filter(c => c?.visible);
        this._hidden.forEach(c => c.hide());

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
        this._hidden.forEach(c => c.show());
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
        // The Inter typeface was installed after GNOME started, so GNOME has not seen it and draws
        // its own text in another face than the apps. Hand it the file, then restyle.
        try {
            const font = GLib.build_filenamev([GLib.get_home_dir(), '.local/share/fonts/Inter.ttf']);
            if (Main.panel.get_pango_context().get_font_map().add_font_file(font))
                Main.loadTheme();
        } catch (e) {
            console.warn(`Lethe fonts: ${e.message}`);
        }
        // Motion. GNOME switches all animation off when there is no graphics card, and Lethe keeps it
        // off while its autopilot reads the screen. Neither holds from here on: this VM draws well
        // over sixty frames a second in software, so windows may open, close and move as designed.
        new Gio.Settings({schema_id: 'org.gnome.desktop.interface'}).set_boolean('enable-animations', true);
        this._animated = !St.Settings.get().enable_animations;
        if (this._animated)
            St.Settings.get().uninhibit_animations();
        this._dock = new Dock(scale);
        this._bar = new TopBar(this.dir);
        this._clipboard = new Clipboard();
        // When Tor connects, Tails switches wallpapers (see setup.sh). Lethe watches for that from
        // outside, but a large window can cover the wallpaper: so the top bar, which nothing covers,
        // lights up for a few seconds as well. It is also how you see that the connection is made.
        this._background = new Gio.Settings({schema_id: 'org.gnome.desktop.background'});
        this._background.connectObject('changed::picture-uri', () => this._connected(), this);
        this._connected();
        // Lethe used the Looking Glass console once, to load this. Close it for the rest of the session.
        new Gio.Settings({schema_id: 'org.gnome.shell'}).set_boolean('development-tools', false);
    }

    _connected() {
        if (!this._background.get_string('picture-uri').endsWith('lethe-online.png') || this._lit)
            return;
        Main.panel.add_style_class_name('lethe-online');
        this._lit = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 6000, () => {
            Main.panel.remove_style_class_name('lethe-online');
            this._lit = -1;                           // once per session
            return GLib.SOURCE_REMOVE;
        });
    }

    disable() {
        this._background?.disconnectObject(this);
        if (this._lit > 0)
            GLib.source_remove(this._lit);
        Main.panel.remove_style_class_name('lethe-online');
        this._background = this._lit = null;
        this._clipboard?.destroy();
        this._bar?.destroy();
        this._dock?.destroy();
        if (this._animated)
            St.Settings.get().inhibit_animations();
        this._clipboard = this._bar = this._dock = null;
        Main.layoutManager.uiGroup.remove_style_class_name('lethe');
    }
}
