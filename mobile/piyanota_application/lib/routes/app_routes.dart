/// Named route constants. Onboarding itself is the app's `home` (not a
/// named route) since it's a one-time gate, not something re-navigated to.
class AppRoutes {
  AppRoutes._();

  static const login = '/login';
  static const signUp = '/sign-up';
  static const passwordReset = '/password-reset';
  static const scoreLibrary = '/library';
}
