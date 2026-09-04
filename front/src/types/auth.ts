export interface AuthUser {
  id: string;
  username: string;
}

export interface AuthPayload {
  token: string;
  expires_at: string;
  user: AuthUser;
}
