import 'dart:async';

import 'package:flutter/foundation.dart';

import '../models/voice_part.dart';
import 'piano_octave_store.dart';
import 'piano_settings_api.dart';

typedef TimerFactory = Timer Function(Duration delay, void Function() run);

/// Octave sync with PIYA-321 (PIYA-218 AC 40-48). The keyboard always renders
/// and plays from the local octave; nothing here is ever awaited by the UI,
/// and every failure leaves the local value in place.
class PianoSyncService {
  PianoSyncService({
    required this.api,
    required this.store,
    this.onSessionExpired,
    TimerFactory? timer,
  }) : _timer = timer ?? Timer.new;

  static const Duration debounce = Duration(milliseconds: 500);

  /// First retry wait; doubles per failure.
  static const Duration retryBase = Duration(seconds: 2);

  /// Past this the pending flag waits for the next modal open (AC 47).
  static const int maxRetries = 5;

  final PianoSettingsApi api;
  final PianoOctaveStore store;

  /// 401: the app's session-expiry flow (AC 46).
  final void Function()? onSessionExpired;
  final TimerFactory _timer;

  /// The signed-in user's voice, for the server's default (AC 2).
  VoicePart? voice;

  Timer? _pending;
  int _failures = 0;
  bool _busy = false;
  bool _rerun = false;

  /// Modal open (AC 40-41). Returns the server octave when it was adopted
  /// into local storage, else null; the caller decides whether the UI may
  /// show it now (AC 42).
  Future<int?> reconcile() async {
    final PianoSettings server;
    try {
      server = await api.get(voice);
    } on PianoSettingsException catch (e) {
      await _fail(e);
      return null;
    }
    // Read after the GET: an octave step made while it was in flight must win.
    final saved = await store.loadSaved();
    final at = server.updatedAt;
    if (at == null || (saved != null && saved.updatedAt.isAfter(at))) {
      if (saved != null) await _push();
      return null;
    }
    if (saved == null || at.isAfter(saved.updatedAt)) {
      await store.adopt(server.octave, at);
      await store.setPending(false);
      return server.octave;
    }
    await store.setPending(false); // equal timestamps: server already has it
    return null;
  }

  /// The local octave just changed (AC 43): one PUT after the last change.
  Future<void> localChanged() async {
    await store.setPending(true);
    _pending?.cancel();
    _pending = _timer(debounce, () => unawaited(_push()));
  }

  /// Modal close or app background (AC 44). [force] sends even when nothing
  /// changed, for the AC 28 save on close.
  Future<void> flush({bool force = false}) async {
    if (force) await store.setPending(true);
    if (force || (_pending?.isActive ?? false) || await store.isPending()) {
      await _push();
    }
  }

  void dispose() => _pending?.cancel();

  Future<void> _push() async {
    _pending?.cancel();
    if (_busy) {
      _rerun = true;
      return;
    }
    _busy = true;
    try {
      do {
        _rerun = false;
        final saved = await store.loadSaved();
        if (saved == null) {
          await store.setPending(false);
          break;
        }
        try {
          final result = await api.put(saved.octave, saved.updatedAt, voice);
          _failures = 0;
          final now = await store.loadSaved();
          // A newer local change made meanwhile wins; its own PUT follows.
          if (now?.updatedAt == saved.updatedAt) {
            final at = result.updatedAt;
            if (result.octave != saved.octave && at != null) {
              await store.adopt(result.octave, at); // AC 45
            }
            await store.setPending(false);
          }
        } on PianoSettingsException catch (e) {
          await _fail(e);
        }
      } while (_rerun);
    } finally {
      _busy = false;
    }
  }

  Future<void> _fail(PianoSettingsException e) async {
    switch (e) {
      case PianoSettingsSessionExpiredException():
        onSessionExpired?.call();
      case PianoSettingsRejectedException(:final code):
        // AC 48: a client bug; retrying would repeat it.
        debugPrint('Piano: sync rejected ($code); local octave kept');
        await store.setPending(false);
      case PianoSettingsNetworkException() || PianoSettingsServerException():
        _failures++;
        if (_failures <= maxRetries && await store.isPending()) {
          _pending?.cancel();
          _pending = _timer(
            retryBase * (1 << (_failures - 1)),
            () => unawaited(_push()),
          );
        }
    }
  }
}
