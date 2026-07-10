import type { NextAuthOptions, User } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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

type OperatorUser = User & {
  accessToken?: string;
  workspaceId?: string;
  workspaceName?: string;
  workspaceRole?: string;
  legacy?: boolean;
};

async function authenticateWithApi(email: string, password: string): Promise<OperatorUser | null> {
  const response = await fetch(`${API_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
    cache: "no-store",
  });

  if (!response.ok) return null;
  const data = (await response.json()) as ApiAuthResponse;

  return {
    id: data.user.id,
    email: data.user.email,
    name: data.user.name,
    image: data.user.image_url,
    accessToken: data.access_token,
    workspaceId: data.workspace.id,
    workspaceName: data.workspace.name,
    workspaceRole: data.workspace.role,
  };
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
          const apiUser = await authenticateWithApi(email, password);
          if (apiUser) return apiUser;
        } catch {
          // Keep the temporary Phase 1 admin fallback available during migration.
        }

        const validEmail = process.env.AUTH_EMAIL?.trim().toLowerCase();
        const validPassword = process.env.AUTH_PASSWORD;
        if (email === validEmail && password === validPassword) {
          return {
            id: "legacy-admin",
            email: validEmail,
            name: "Admin",
            legacy: true,
          } satisfies OperatorUser;
        }
        return null;
      },
    }),
  ],
  callbacks: {
    async jwt({ token, user, trigger, session }) {
      if (user) {
        const operatorUser = user as OperatorUser;
        token.sub = operatorUser.id;
        token.accessToken = operatorUser.accessToken;
        token.workspaceId = operatorUser.workspaceId;
        token.workspaceName = operatorUser.workspaceName;
        token.workspaceRole = operatorUser.workspaceRole;
        token.legacy = operatorUser.legacy ?? false;
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
      session.legacy = token.legacy === true;
      return session;
    },
  },
  session: {
    strategy: "jwt",
    maxAge: 24 * 60 * 60,
  },
  pages: {
    signIn: "/login",
  },
  secret: process.env.NEXTAUTH_SECRET,
};
