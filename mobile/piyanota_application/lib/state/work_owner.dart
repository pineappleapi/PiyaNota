import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Which account the work kept on the device belongs to: the stored scan
/// jobs (ScanJobStore) and any export still running in the background.
///
/// There is no auto-login yet (PIYA-214), so every cold start goes through
/// Login. Without this, that login could not tell "the same person again"
/// from "someone else" and had to wipe a running export, the scans' result
/// notifications and the stored jobs every time. Now only a different
/// account's login clears them; logout still clears everything.
///
/// SharedPreferences, like ScanJobStore: an account id is not a secret.
/// Errors are logged and read as "no owner", which makes the next login
/// clear: losing the work is the safe side of not knowing whose it is.
class WorkOwnerStore {
  const WorkOwnerStore();

  @visibleForTesting
  static const String storageKey = 'work_owner_v1';

  Future<int?> load() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      return prefs.getInt(storageKey);
    } on Object catch (e) {
      debugPrint('Work owner not read: $e');
      return null;
    }
  }

  Future<void> save(int userId) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setInt(storageKey, userId);
    } on Object catch (e) {
      debugPrint('Work owner not saved: $e');
    }
  }

  Future<void> clear() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove(storageKey);
    } on Object catch (e) {
      debugPrint('Work owner not cleared: $e');
    }
  }
}

final workOwnerStoreProvider = Provider<WorkOwnerStore>(
  (ref) => const WorkOwnerStore(),
);

/// True once someone has logged in during this run of the app, false again
/// after logout. Stored scans are restored and polled, and the scans'
/// foreground service runs, only while it is true: before login there is
/// no session token to poll with, and the jobs may be another account's.
///
/// In memory on purpose: a Flutter engine kept alive for background work
/// keeps it, and a new process starts at Login (no auto-login, PIYA-214).
final signedInProvider = NotifierProvider<SignedIn, bool>(SignedIn.new);

class SignedIn extends Notifier<bool> {
  @override
  bool build() => false;

  // A setter would read as a field; this is a state change.
  // ignore: use_setters_to_change_properties
  void set(bool value) => state = value;
}
