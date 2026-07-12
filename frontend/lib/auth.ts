import { createHmac } from "node:crypto";

import type { NextAuthOptions, Profile, User } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import GitHubProvider from "next-auth/providers/github";
import GoogleProvider from "next-auth/providers/google";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const googleClientId = process.env.GOOGLE_CLIENT_ID;
const googleClientSecret = process.env.GOOGLE_CLIENT_SECRET;
const githubClientId = process.env.GITHUB_ID;
const githubClientSecret = process.env.GITHUB_SECRET;

type WorkspaceSummary = {
  id: string;
  name: string;
  slug: string;
  role: string;
  status: string;
};

type ApiAuthResponse = {
  access_token: string;
  expires_in: number;
  user: {
    id: string;
    email: string;
    name: string | null;
    image_url: string | null;
  };
  workspace: WorkspaceSummary;
};

type OAuthLinkRequired = {
  link_required: true;
  link_token: string;
  email: string;
  expires_in: number;
};

type OAuthExchangeResult = ApiAuthResponse | OAuthLinkRequired;

type OperatorUser = User & {
  accessToken?: string;
  workspaceId?: string;
  workspaceName?: string;
  workspaceRole?: string;
  oauthLinkRequired?: boolean;
  oauthLinkToken?: string;
  oauthLinkEmail?: string;
};

type GoogleProfile = Profile & {
  sub?: string;
  email?: string;
  email_verified?: boolean;
  picture?: string;
};

type GitHubEmail = {
  email: string;
  primary: boolean;
  verified: boolean;
  visibility: string | null;
};

function applyApiAuth(user: OperatorUser, data: ApiAuthResponse) {
  user.id = data.user.id;
  user.email = data.user.email;
  user.name = data.user.name;
  user.image = data.user.image_url;
  user.accessToken = data.access_token;
  user.workspaceId = data.workspace.id;
  user.workspaceName = data.workspace.name;
  user.workspaceRole = data.workspace.role;
  user.oauthLinkRequired = false;
  user.oauthLinkToken = undefined;
  user.oauthLinkEmail = undefined;
}

async function authenticateWithApi(email: string, password: string): Promise<OperatorUser | null> {
  const response = await fetch(`${API_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
    cache: "no-store",
  });

  if (!response.ok) return null;
  const data = (await response.json()) as ApiAuthResponse;
  const user: OperatorUser = {
    id: data.user.id,
    email: data.user.email,
    name: data.user.name,
    image: data.user.image_url,
  };
  applyApiAuth(user, data);
  return user;
}

async function verifiedGitHubEmail(accessToken: string): Promise<string | null> {
  const response = await fetch("https://api.github.com/user/emails", {
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "SERP-Strategists",
    },
    cache: "no-store",
  });
  if (!response.ok) return null;

  const emails = (await response.json()) as GitHubEmail[];
  const verified = emails.filter((item) => item.verified);
  return (verified.find((item) => item.primary) ?? verified[0])?.email?.toLowerCase() ?? null;
}

async function exchangeOAuthWithApi(input: {
  provider: "google" | "github";
  providerAccountId: string;
  email: string;
  emailVerified: boolean;
  name?: string | null;
  imageUrl?: string | null;
}): Promise<OAuthExchangeResult> {
  const bridgeSecret = process.env.OAUTH_BRIDGE_SECRET;
  if (!bridgeSecret || bridgeSecret.length < 32) {
    throw new Error("OAuth bridge is not configured");
  }

  const timestamp = Math.floor(Date.now() / 1000).toString();
  const email = input.email.trim().toLowerCase();
  const message = JSON.stringify([
    timestamp,
    input.provider,
    input.providerAccountId,
    email,
    input.emailVerified,
  ]);
  const signature = createHmac("sha256", bridgeSecret).update(message).digest("hex");
  const response = await fetch(`${API_URL}/auth/oauth/exchange`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-OAuth-Bridge-Timestamp": timestamp,
      "X-OAuth-Bridge-Signature": signature,
    },
    body: JSON.stringify({
      provider: input.provider,
      provider_account_id: input.providerAccountId,
      email,
      email_verified: input.emailVerified,
      name: input.name || undefined,
      image_url: input.imageUrl || undefined,
    }),
    cache: "no-store",
  });

  const body = (await response.json().catch(() => null)) as
    | OAuthExchangeResult
    | { detail?: string }
    | null;
  if (!response.ok) {
    throw new Error(
      body && "detail" in body && typeof body.detail === "string"
        ? body.detail
        : "OAuth account exchange failed",
    );
  }
  return body as OAuthExchangeResult;
}

async function validateWorkspaceSelection(
  accessToken: string,
  workspaceId: string,
): Promise<WorkspaceSummary | null> {
  const response = await fetch(`${API_URL}/workspaces`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });
  if (!response.ok) return null;

  const workspaces = (await response.json()) as WorkspaceSummary[];
  return workspaces.find((workspace) => workspace.id === workspaceId && workspace.status === "active") ?? null;
}

export const authOptions: NextAuthOptions = {
  providers: [
    CredentialsProvider({
      name: "Email and password",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        const email = credentials?.email?.trim().toLowerCase();
        const password = credentials?.password;
        if (!email || !password) return null;

        try {
          return await authenticateWithApi(email, password);
        } catch {
          return null;
        }
      },
    }),
    ...(googleClientId && googleClientSecret
      ? [GoogleProvider({ clientId: googleClientId, clientSecret: googleClientSecret })]
      : []),
    ...(githubClientId && githubClientSecret
      ? [
          GitHubProvider({
            clientId: githubClientId,
            clientSecret: githubClientSecret,
            authorization: { params: { scope: "read:user user:email" } },
          }),
        ]
      : []),
  ],
  callbacks: {
    async signIn({ user, account, profile }) {
      if (!account || account.provider === "credentials") return true;
      if (account.provider !== "google" && account.provider !== "github") return false;

      try {
        let email: string | null = null;
        let emailVerified = false;
        let name = user.name;
        let imageUrl = user.image;

        if (account.provider === "google") {
          const googleProfile = profile as GoogleProfile;
          email = googleProfile.email?.toLowerCase() ?? user.email?.toLowerCase() ?? null;
          emailVerified = googleProfile.email_verified === true;
          name = googleProfile.name ?? user.name;
          imageUrl = googleProfile.picture ?? user.image;
        } else {
          if (!account.access_token) return "/login?error=OAuthEmailUnavailable";
          email = await verifiedGitHubEmail(account.access_token);
          emailVerified = Boolean(email);
          name = profile?.name ?? user.name;
          imageUrl = user.image;
        }

        if (!email || !emailVerified) return "/login?error=OAuthEmailUnverified";

        const result = await exchangeOAuthWithApi({
          provider: account.provider,
          providerAccountId: account.providerAccountId,
          email,
          emailVerified,
          name,
          imageUrl,
        });
        const operatorUser = user as OperatorUser;

        if ("link_required" in result && result.link_required) {
          operatorUser.oauthLinkRequired = true;
          operatorUser.oauthLinkToken = result.link_token;
          operatorUser.oauthLinkEmail = result.email;
          operatorUser.email = result.email;
          operatorUser.accessToken = undefined;
          operatorUser.workspaceId = undefined;
          operatorUser.workspaceName = undefined;
          operatorUser.workspaceRole = undefined;
        } else {
          applyApiAuth(operatorUser, result as ApiAuthResponse);
        }
        return true;
      } catch {
        return "/login?error=OAuthSignin";
      }
    },
    async jwt({ token, user, trigger, session }) {
      if (user) {
        const operatorUser = user as OperatorUser;
        token.sub = operatorUser.id;
        token.accessToken = operatorUser.accessToken;
        token.workspaceId = operatorUser.workspaceId;
        token.workspaceName = operatorUser.workspaceName;
        token.workspaceRole = operatorUser.workspaceRole;
        token.oauthLinkRequired = operatorUser.oauthLinkRequired ?? false;
        token.oauthLinkToken = operatorUser.oauthLinkToken;
        token.oauthLinkEmail = operatorUser.oauthLinkEmail;
      }

      if (
        trigger === "update" &&
        typeof token.accessToken === "string" &&
        typeof session?.workspaceId === "string"
      ) {
        const selected = await validateWorkspaceSelection(token.accessToken, session.workspaceId);
        if (selected) {
          token.workspaceId = selected.id;
          token.workspaceName = selected.name;
          token.workspaceRole = selected.role;
        }
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user) session.user.id = token.sub ?? "";
      session.accessToken = typeof token.accessToken === "string" ? token.accessToken : undefined;
      session.workspaceId = typeof token.workspaceId === "string" ? token.workspaceId : undefined;
      session.workspaceName = typeof token.workspaceName === "string" ? token.workspaceName : undefined;
      session.workspaceRole = typeof token.workspaceRole === "string" ? token.workspaceRole : undefined;
      session.oauthLinkRequired = token.oauthLinkRequired === true;
      session.oauthLinkToken = typeof token.oauthLinkToken === "string" ? token.oauthLinkToken : undefined;
      session.oauthLinkEmail = typeof token.oauthLinkEmail === "string" ? token.oauthLinkEmail : undefined;
      return session;
    },
  },
  session: {
    strategy: "jwt",
    maxAge: 24 * 60 * 60,
  },
  pages: {
    signIn: "/login",
    error: "/login",
  },
  secret: process.env.NEXTAUTH_SECRET,
};
