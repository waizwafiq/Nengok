import axios from "axios";

const baseURL = import.meta.env.VITE_NENGOK_API_BASE_URL ?? "/api/v1";

export const TOKEN_STORAGE_KEY = "nengok_token";

export function getStoredToken(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function storeToken(token: string): void {
  window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

export function clearStoredToken(): void {
  window.localStorage.removeItem(TOKEN_STORAGE_KEY);
}

export const apiClient = axios.create({
  baseURL,
  timeout: 10_000,
});

apiClient.interceptors.request.use((config) => {
  const token = getStoredToken();
  if (token) {
    config.headers.set("Authorization", `Bearer ${token}`);
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401 && typeof window !== "undefined") {
      clearStoredToken();
      const redirect = `${window.location.pathname}${window.location.search}`;
      if (window.location.pathname !== "/login") {
        window.location.replace(`/login?redirect=${encodeURIComponent(redirect)}`);
      }
    }
    return Promise.reject(error);
  },
);
