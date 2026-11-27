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
import GObject from 'gi://GObject';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Dash} from 'resource:///org/gnome/shell/ui/dash.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const CLIP_LABEL = 'LETHECLIP';
const MAX_CLIP = 32 * 1024 * 1024;

// The dock is GNOME's own dash (the one in the overview), shown on the desktop as well. Everything
// in it is GNOME's: dragging to reorder, right-click menus, running marks, labels, keyboard focus.
// Two things differ: its icons have one fixed size, matched to the screen's scale (the stock dash
// only knows 48 and 64), and the button for the app grid is drawn as a tile like the apps.
const LetheDash = GObject.registerClass(
class LetheDash extends Dash {
    _init(size, gridIcon) {
        this._size = size;
        super._init();
        this.iconSize = size;
        const grid = this._showAppsIcon.icon;
        grid.createIcon = s => new St.Icon({gicon: gridIcon, icon_size: s, style_class: 'show-apps-icon', track_hover: true});
        grid.setIconSize(1);        // drop the stock symbol...
        grid.setIconSize(size);     // ...and draw ours
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

class Dock {
    constructor(scale, dir) {
        this._scale = scale;
        this._dash = new LetheDash(this._size(), Gio.icon_new_for_string(dir.get_child('apps.svg').get_path()));
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
        // The Inter typeface was installed after GNOME started, so GNOME has not seen it and draws
        // its own text in another face than the apps. Hand it the file, then restyle.
        try {
            const font = GLib.build_filenamev([GLib.get_home_dir(), '.local/share/fonts/Inter.ttf']);
            if (Main.panel.get_pango_context().get_font_map().add_font_file(font))
                Main.loadTheme();
        } catch (e) {
            console.warn(`Lethe fonts: ${e.message}`);
        }
        this._dock = new Dock(scale, this.dir);
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
