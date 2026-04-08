// AppStateContextProvider.js
import React, { createContext, useState } from 'react';
import { USER_DISPLAY_NAME_KEY } from '../utils/accountDisplayName';

const createContextProvider = (Context) => ({ children }) => {
  const [inputText, setInputText] = useState('');
  const [modelSelect, setModel] = useState('copilot');
  const [newMessage, setNewMessage] = useState('');
  const [conversation, setConversation] = useState([]);
  const [submitted] = useState(false);
  const [chatConvo, setChatConvo] = useState([]);
  const [inputLocationText, setInputLocationText] = useState('');

  // Both the selected user ID AND the full service users list live in context.
  // This means:
  //   1. The dropdown selection survives tab switches (selectedServiceUser persists)
  //   2. The dropdown options survive tab switches (serviceUsers persists)
  //      so the select never briefly renders empty and "forget" the selected value.
  const [selectedServiceUser, setSelectedServiceUser] = useState('');
  const [serviceUsers, setServiceUsers] = useState([]);
  const [conversationID, setConversationID] = useState('');

  // Sidebar panels (socket goals_update); live in context so they survive Chat + Explore unmount (e.g. Chat history).
  const [goals, setGoals] = useState([]);
  const [resources, setResources] = useState([]);

  const [organization, setOrganization] = useState(() => {
    return localStorage.getItem('organization') || 'cspnj';
  });

  const [user, setUser] = useState(() => {
    const storedToken = localStorage.getItem('accessToken');
    const storedRole = localStorage.getItem('userRole');
    const storedUsername = localStorage.getItem('username');
    if (storedToken && storedRole && storedUsername) {
      const storedDisplayName = localStorage.getItem(USER_DISPLAY_NAME_KEY) || '';
      return {
        isAuthenticated: true,
        username: storedUsername,
        role: storedRole,
        token: storedToken,
        displayName: storedDisplayName.trim(),
      };
    }
    return { username: '', isAuthenticated: false, token: null, role: null, displayName: '' };
  });

  const resetContext = () => {
    setInputText('');
    setNewMessage('');
    setConversation([]);
    setChatConvo([]);
    setInputLocationText('');
    setGoals([]);
    setResources([]);
    // Intentionally NOT resetting selectedServiceUser or serviceUsers —
    // those should survive both tab switches and new sessions.
  };

  const contextValue = {
    inputText, setInputText,
    modelSelect, setModel,
    inputLocationText, setInputLocationText,
    newMessage, setNewMessage,
    conversation, setConversation,
    submitted,
    chatConvo, setChatConvo,
    organization, setOrganization,
    user, setUser,
    resetContext,
    selectedServiceUser, setSelectedServiceUser,
    serviceUsers, setServiceUsers,
    conversationID, setConversationID,
    goals, setGoals,
    resources, setResources,
  };

  return <Context.Provider value={contextValue}>{children}</Context.Provider>;
};

export const WellnessContext = createContext();
export const WellnessContextProvider = createContextProvider(WellnessContext);