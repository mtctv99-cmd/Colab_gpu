"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarFooter,
  SidebarHeader,
} from "@/components/ui/sidebar";
import {
  LayoutDashboard,
  Users,
  Mic,
  Server,
  Key,
  Clock,
  LogOut,
  ArrowLeft,
  Satellite,
} from "lucide-react";

const tabs = [
  { id: "overview", label: "Tong quan", icon: LayoutDashboard, path: "/admin" },
  { id: "accounts", label: "Colab Workers", icon: Server, path: "/admin/accounts" },
  { id: "nodes", label: "Ve tinh", icon: Satellite, path: "/admin/nodes" },
  { id: "tasks", label: "Tac vu", icon: Clock, path: "/admin/tasks" },
  { id: "users", label: "Nguoi dung", icon: Users, path: "/admin/users" },
  { id: "apikeys", label: "API Keys", icon: Key, path: "/admin/apikeys" },
  { id: "voices", label: "Giong noi", icon: Mic, path: "/admin/voices" },
];

export default function AdminSidebar() {
  const pathname = usePathname();
  const router = useRouter();

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="p-4 flex flex-row items-center justify-between">
        <Link href="/dashboard" className="font-bold text-lg">
          clone<span className="text-primary">.</span>tts
          <span className="ml-2 text-xs font-mono text-muted-foreground uppercase tracking-wider">ADMIN</span>
        </Link>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Admin Menu</SidebarGroupLabel>
          <SidebarMenu>
            {tabs.map((t) => (
              <SidebarMenuItem key={t.id}>
                <SidebarMenuButton
                  isActive={pathname === t.path}
                  tooltip={t.label}
                  render={<Link href={t.path} className="flex items-center w-full" />}
                >
                  <t.icon />
                  <span>{t.label}</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            ))}
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton render={<Link href="/dashboard" className="flex items-center w-full" />}>
              <ArrowLeft />
              <span>Về Dashboard</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton onClick={() => { localStorage.clear(); router.push("/"); }}>
              <LogOut />
              <span>Đăng xuất</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  );
}
