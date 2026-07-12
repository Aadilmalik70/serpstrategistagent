import "next-auth";
import "next-auth/jwt";

declare module "next-auth" {
  interface Session {
    accessToken?: string;
    workspaceId?: string;
    workspaceName?: string;
    workspaceRole?: string;
    oauthLinkRequired?: boolean;
    oauthLinkToken?: string;
    oauthLinkEmail?: string;
    user?: {
      id: string;
      name?: string | null;
      email?: string | null;
      image?: string | null;
    };
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    accessToken?: string;
    workspaceId?: string;
    workspaceName?: string;
    workspaceRole?: string;
    oauthLinkRequired?: boolean;
    oauthLinkToken?: string;
    oauthLinkEmail?: string;
  }
}
