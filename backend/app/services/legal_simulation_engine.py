"""
Motor de Simulação Jurídica Colegiada (JuS-Sim)
Substituto de alta precisão do OASIS social para julgamentos e conflitos judiciais brasileiros.

Modela com fidelidade:
1. Tribunais Colegiados (Câmaras, Turmas, Plenários de STF, STJ, TJs, TRFs)
2. Papéis Processuais: Relator, Revisor/Vogais, Ministério Público, Patronos (Autor e Réu), Peritos
3. Fases do Rito: Relatório, Preliminares, Sustentações Orais, Parecer MP, Voto do Relator, Divergências, Debates e Proclamação do Acórdão
4. Fundamentação Jurídica Vinculante: Citação de Leis (CF, CPC, CC, CP, CLT, CDC) e Súmulas/Temas STF e STJ
"""

import os
import sys
import json
import time
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime

from openai import OpenAI
from ..utils.openai_chat_compat import create_chat_completion, extract_chat_completion_text

try:
    from action_logger import PlatformActionLogger, SimulationLogManager
except ImportError:
    scripts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../scripts"))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from action_logger import PlatformActionLogger, SimulationLogManager

# Mapeamento de papéis jurídicos
ROLE_RELATOR = "Desembargador/Ministro Relator"
ROLE_VOGAL_1 = "1º Magistrado Vogal (Revisor)"
ROLE_VOGAL_2 = "2º Magistrado Vogal"
ROLE_MP = "Ministério Público (Fiscal da Ordem Jurídica)"
ROLE_ADV_AUTOR = "Advogado da Parte Autora / Agravante"
ROLE_ADV_REU = "Advogado da Parte Ré / Agravada"
ROLE_PERITO = "Perito Judicial / Assistente Técnico"


class LegalAgent:
    """Representação de um agente jurídico (Magistrado, Promotor, Advogado, Perito)"""
    def __init__(
        self,
        agent_id: int,
        name: str,
        role: str,
        hermeneutic_profile: str,
        bio: str,
        persona: str,
        bias: str = "imparcial"
    ):
        self.agent_id = agent_id
        self.name = name
        self.role = role
        self.hermeneutic_profile = hermeneutic_profile
        self.bio = bio
        self.persona = persona
        self.bias = bias


class LegalSimulationEngine:
    """Motor de execução de simulação jurídica colegiada"""

    def __init__(
        self,
        config: Dict[str, Any],
        simulation_dir: str,
        twitter_logger: Optional[PlatformActionLogger] = None,
        reddit_logger: Optional[PlatformActionLogger] = None,
        main_logger: Optional[SimulationLogManager] = None,
        max_rounds: Optional[int] = None
    ):
        self.config = config
        self.simulation_dir = simulation_dir
        self.colegiado_logger = twitter_logger  # Sessão Plenária / Votos
        self.tribuna_logger = reddit_logger     # Tribuna de Debates / Sustentações
        self.main_logger = main_logger
        self.max_rounds = max_rounds or config.get("time_config", {}).get("total_simulation_hours", 40)
        if self.max_rounds > 40:
            self.max_rounds = 40  # Limite ótimo para cobertura completa dos ritos

        self.simulation_requirement = config.get("simulation_requirement", "Simulação Jurídica")
        self.agents: List[LegalAgent] = []
        self.simulation_context: List[Dict[str, Any]] = []
        self.ipc_active = True
        
        # Cliente LLM
        self._setup_llm()
        self._setup_agents()

    def log(self, message: str, level: str = "info"):
        if self.main_logger:
            self.main_logger.log(f"[JuS-Engine] {message}", level)
        else:
            print(f"[JuS-Engine] {message}")

    def _setup_llm(self):
        """Configura o cliente LLM com base nas variáveis de ambiente do admin"""
        api_key = os.environ.get("LLM_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
        base_url = os.environ.get("LLM_BASE_URL", "") or os.environ.get("OPENAI_API_BASE_URL", "")
        self.model_name = os.environ.get("LLM_MODEL_NAME", "gemini-2.5-flash")

        if not api_key:
            api_key = "dummy-key"

        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url

        self.client = OpenAI(**client_kwargs)

    def _setup_agents(self):
        """Instancia os agentes jurídicos com base na configuração ou perfis salvos"""
        agent_configs = self.config.get("agent_configs", [])
        
        # Perfis pré-definidos para garantir rito completo
        default_roles = [
            (ROLE_RELATOR, "Legalista e Focado na Jurisprudência Dominante do STJ/STF", "Relator encarregado de conduzir o voto condutor com rigor técnico e citação expressa de artigos."),
            (ROLE_ADV_AUTOR, "Defensor Combustivo dos Direitos do Autor", "Sustenta a tese da petição inicial, demonstrando nexo de causalidade, dano e violação legal expressa."),
            (ROLE_ADV_REU, "Estrategista de Defesa Formal e Mérito", "Argui preliminares processuais, ausência de provas, excludentes de responsabilidade e pede a improcedência total."),
            (ROLE_MP, "Fiscal da Ordem Jurídica (Custos Legis)", "Atua com estrita imparcialidade zelando pela higidez constitucional e aplicação correta da legislação."),
            (ROLE_VOGAL_1, "Hermenêutica Garantista e Finalista / Pró-Consumidor", "Magistrado revisor que pondera princípios constitucionais e pode abrir divergência se houver excesso de formalismo."),
            (ROLE_VOGAL_2, "Pragmatista e Focado na Análise Econômica do Direito", "Magistrado vogal focado na segurança jurídica, impacto sistêmico e precedentes vinculantes."),
            (ROLE_PERITO, "Assistente Técnico / Perito Judicial", "Analisa a verossimilhança probatória, laudos e documentos técnicos acostados aos autos.")
        ]

        if not agent_configs:
            # Fallback para agentes padrão se a lista vier vazia
            for i, (role, herm, bio) in enumerate(default_roles):
                name = f"Dr(a). {role.split(' ')[0]} {chr(65+i)}"
                self.agents.append(LegalAgent(
                    agent_id=i,
                    name=name,
                    role=role,
                    hermeneutic_profile=herm,
                    bio=bio,
                    persona=f"{name} atua como {role}. Linha de atuação: {herm}. {bio}"
                ))
            return

        for idx, ac in enumerate(agent_configs):
            role_idx = idx % len(default_roles)
            default_role, default_herm, default_bio = default_roles[role_idx]
            
            name = ac.get("entity_name") or ac.get("name") or f"Operador_{idx}"
            bio = ac.get("bio") or default_bio
            persona = ac.get("persona") or bio
            
            # Se o nome já indicar um papel
            role = default_role
            if "relator" in name.lower():
                role = ROLE_RELATOR
            elif "autor" in name.lower() or "agravante" in name.lower():
                role = ROLE_ADV_AUTOR
            elif "réu" in name.lower() or "reu" in name.lower() or "agravado" in name.lower():
                role = ROLE_ADV_REU
            elif "promotor" in name.lower() or "procurador" in name.lower() or "mp" in name.lower():
                role = ROLE_MP
            elif "vogal" in name.lower() or "revisor" in name.lower() or "desembargador" in name.lower():
                role = ROLE_VOGAL_1 if idx % 2 == 0 else ROLE_VOGAL_2

            self.agents.append(LegalAgent(
                agent_id=idx,
                name=name,
                role=role,
                hermeneutic_profile=default_herm,
                bio=bio,
                persona=persona
            ))

    async def _call_llm_for_action(self, system_prompt: str, user_prompt: str) -> str:
        """Gera a manifestação jurídica via LLM"""
        try:
            resp = create_chat_completion(
                self.client,
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_tokens=1000
            )
            return extract_chat_completion_text(resp)
        except Exception as e:
            self.log(f"Falha na chamada LLM: {e}. Usando fundamentação padrão.", "warning")
            return "Em conformidade com os princípios da legalidade e segurança jurídica, ratifico as manifestações anteriores e os termos da legislação processual aplicável."

    async def run_simulation(self):
        """Executa a simulação judicial completa pelas 40 rodadas processuais"""
        self.log(f"Iniciando Sessão de Julgamento Simulado com {len(self.agents)} agentes jurídicos...")
        self.log(f"Caso/Objeto: {self.simulation_requirement[:120]}...")

        # Inicia loggers
        if self.colegiado_logger:
            self.colegiado_logger.log_simulation_start(self.config)
        if self.tribuna_logger:
            self.tribuna_logger.log_simulation_start(self.config)

        total_actions = 0

        # Identifica os agentes chave
        relator = next((a for a in self.agents if a.role == ROLE_RELATOR), self.agents[0])
        adv_autor = next((a for a in self.agents if a.role == ROLE_ADV_AUTOR), self.agents[min(1, len(self.agents)-1)])
        adv_reu = next((a for a in self.agents if a.role == ROLE_ADV_REU), self.agents[min(2, len(self.agents)-1)])
        mp = next((a for a in self.agents if a.role == ROLE_MP), self.agents[min(3, len(self.agents)-1)])
        vogais = [a for a in self.agents if "Vogal" in a.role]
        if not vogais:
            vogais = [self.agents[min(4, len(self.agents)-1)]]

        recent_debate_context: List[str] = []

        for current_round in range(1, self.max_rounds + 1):
            if self.colegiado_logger:
                self.colegiado_logger.log_round_start(current_round, current_round)
            if self.tribuna_logger:
                self.tribuna_logger.log_round_start(current_round, current_round)

            round_actions = 0

            # -------------------------------------------------------------
            # FASE 1: Relatório & Fixação das Controvérsias (Rounds 1 - 5)
            # -------------------------------------------------------------
            if current_round <= 5:
                if current_round == 1:
                    # Relator abre o relatório
                    sys_p = (
                        "Você é o Desembargador Relator em uma sessão de tribunal brasileiro. "
                        "Apresente o RELATÓRIO DO PROCESSO com sobriedade e precisão técnica. "
                        "Sintetize os fatos centrais da causa, os pedidos do autor e os fundamentos da defesa. "
                        "Não emita seu voto ainda, apenas fixe os fatos e a matéria em julgamento."
                    )
                    user_p = f"Objeto da Ação / Conflito:\n{self.simulation_requirement}"
                    content = await self._call_llm_for_action(sys_p, user_p)

                    self.colegiado_logger.log_action(
                        round_num=current_round,
                        agent_id=relator.agent_id,
                        agent_name=relator.name,
                        action_type="CREATE_POST",
                        action_args={
                            "content": f"📋 [RELATÓRIO DO PROCESSO]\n\n{content}",
                            "phase": "Relatório Processual",
                            "role": relator.role
                        }
                    )
                    recent_debate_context.append(f"Relatório: {content[:300]}")
                    round_actions += 1

                elif current_round == 3:
                    # Advogado do Réu argui preliminar de mérito
                    sys_p = (
                        "Você é o Advogado da Parte Ré. Na tribuna, suscite uma questão preliminar ou prejudicial de mérito "
                        "(ex: ilegitimidade passiva, falta de interesse de agir, prescrição/decadência ou incompetência) "
                        "com base no CPC brasileiro."
                    )
                    user_p = f"Contexto da lide:\n{self.simulation_requirement}\nRelatório:\n{recent_debate_context[-1] if recent_debate_context else ''}"
                    content = await self._call_llm_for_action(sys_p, user_p)

                    self.tribuna_logger.log_action(
                        round_num=current_round,
                        agent_id=adv_reu.agent_id,
                        agent_name=adv_reu.name,
                        action_type="CREATE_POST",
                        action_args={
                            "content": f"⚖️ [PRELIMINAR DA DEFESA]\n\n{content}",
                            "phase": "Saneamento e Preliminares",
                            "role": adv_reu.role
                        }
                    )
                    recent_debate_context.append(f"Preliminar Réu: {content[:300]}")
                    round_actions += 1

                elif current_round == 5:
                    # Advogado do Autor replica a preliminar
                    sys_p = (
                        "Você é o Advogado do Autor. Rejeite categoricamente a preliminar arguida pelo Réu, "
                        "demonstrando a presença dos pressupostos processuais e a plena legitimidade e interesse das partes."
                    )
                    user_p = f"Preliminar arguida pelo Réu:\n{recent_debate_context[-1] if recent_debate_context else ''}"
                    content = await self._call_llm_for_action(sys_p, user_p)

                    self.tribuna_logger.log_action(
                        round_num=current_round,
                        agent_id=adv_autor.agent_id,
                        agent_name=adv_autor.name,
                        action_type="CREATE_COMMENT",
                        action_args={
                            "content": f"🗣️ [RÉPLICA DA AUTORIA]\n\n{content}",
                            "phase": "Contraditório das Preliminares",
                            "role": adv_autor.role,
                            "post_id": 1
                        }
                    )
                    round_actions += 1

            # -------------------------------------------------------------
            # FASE 2: Sustentações Orais & Parecer do MP (Rounds 6 - 15)
            # -------------------------------------------------------------
            elif current_round <= 15:
                if current_round == 7:
                    # Sustentação oral da autoria
                    sys_p = (
                        "Você é o Advogado do Autor proferindo sua SUSTENTAÇÃO ORAL na Tribuna. "
                        "Defenda enfaticamente o direito material do autor, cite artigos de lei cabíveis "
                        "(ex: Código Civil, CDC ou CF/88) e precedentes do STJ/STF. Conclua pelo provimento do pedido."
                    )
                    user_p = f"Caso em julgamento:\n{self.simulation_requirement}"
                    content = await self._call_llm_for_action(sys_p, user_p)

                    self.tribuna_logger.log_action(
                        round_num=current_round,
                        agent_id=adv_autor.agent_id,
                        agent_name=adv_autor.name,
                        action_type="CREATE_POST",
                        action_args={
                            "content": f"🎤 [SUSTENTAÇÃO ORAL - AUTORIA]\n\n{content}",
                            "phase": "Sustentação Oral",
                            "role": adv_autor.role
                        }
                    )
                    recent_debate_context.append(f"Sustentação Autor: {content[:300]}")
                    round_actions += 1

                elif current_round == 10:
                    # Sustentação oral da defesa
                    sys_p = (
                        "Você é o Advogado do Réu proferindo sua SUSTENTAÇÃO ORAL perante o Colegiado. "
                        "Apresente as teses de defesa: ausência de prova cabal, excludente de ilicitude, "
                        "caso fortuito/força maior ou estrito cumprimento da lei. Peça a improcedência total."
                    )
                    user_p = f"Caso em julgamento:\n{self.simulation_requirement}\nTeses do Autor:\n{recent_debate_context[-1] if recent_debate_context else ''}"
                    content = await self._call_llm_for_action(sys_p, user_p)

                    self.tribuna_logger.log_action(
                        round_num=current_round,
                        agent_id=adv_reu.agent_id,
                        agent_name=adv_reu.name,
                        action_type="CREATE_POST",
                        action_args={
                            "content": f"🛡️ [SUSTENTAÇÃO ORAL - DEFESA]\n\n{content}",
                            "phase": "Sustentação Oral",
                            "role": adv_reu.role
                        }
                    )
                    recent_debate_context.append(f"Sustentação Réu: {content[:300]}")
                    round_actions += 1

                elif current_round == 13:
                    # Parecer do Ministério Público
                    sys_p = (
                        "Você é o representante do MINISTÉRIO PÚBLICO atuando como Custos Legis (Fiscal da Ordem Jurídica). "
                        "Analise a matéria sob a ótica estrita da constitucionalidade e da legalidade. "
                        "Emita seu PARECER CONCLUSIVO opinando pela procedência, improcedência ou provimento parcial."
                    )
                    user_p = f"Caso em julgamento:\n{self.simulation_requirement}\nDebates na tribuna:\n{chr(10).join(recent_debate_context[-2:])}"
                    content = await self._call_llm_for_action(sys_p, user_p)

                    self.tribuna_logger.log_action(
                        round_num=current_round,
                        agent_id=mp.agent_id,
                        agent_name=mp.name,
                        action_type="CREATE_POST",
                        action_args={
                            "content": f"🏛️ [PARECER DO MINISTÉRIO PÚBLICO]\n\n{content}",
                            "phase": "Parecer Custos Legis",
                            "role": mp.role
                        }
                    )
                    recent_debate_context.append(f"Parecer MP: {content[:300]}")
                    round_actions += 1

            # -------------------------------------------------------------
            # FASE 3: Voto Condutor do Desembargador Relator (Rounds 16 - 22)
            # -------------------------------------------------------------
            elif current_round <= 22:
                if current_round == 17:
                    # O Relator vota preliminares
                    sys_p = (
                        "Você é o Desembargador Relator. Inicie a prolação do seu VOTO analisando e REJEITANDO "
                        "ou acolhendo as preliminares suscitadas pela defesa. Fundamente com base nos artigos do CPC."
                    )
                    user_p = f"Caso:\n{self.simulation_requirement}\nParecer MP:\n{recent_debate_context[-1] if recent_debate_context else ''}"
                    content = await self._call_llm_for_action(sys_p, user_p)

                    self.colegiado_logger.log_action(
                        round_num=current_round,
                        agent_id=relator.agent_id,
                        agent_name=relator.name,
                        action_type="CREATE_POST",
                        action_args={
                            "content": f"📜 [VOTO DO RELATOR - PRELIMINARES]\n\n{content}",
                            "phase": "Julgamento de Preliminares",
                            "role": relator.role
                        }
                    )
                    round_actions += 1

                elif current_round == 20:
                    # O Relator profere o voto de mérito com o dispositivo
                    sys_p = (
                        "Você é o Desembargador Relator. Profira a fundamentação de MÉRITO e o DISPOSITIVO do seu VOTO. "
                        "Cite artigos de lei específicos, jurisprudência do STJ/STF e conclua de forma clara com o dispositivo: "
                        "'VOTO NO SENTIDO DE [DAR PROVIMENTO / NEGAR PROVIMENTO / DAR PARCIAL PROVIMENTO] ao recurso/ação.' "
                        "Fixe indenizações, obrigações e custas sucumbenciais de acordo."
                    )
                    user_p = f"Caso:\n{self.simulation_requirement}\nDebates:\n{chr(10).join(recent_debate_context)}"
                    content = await self._call_llm_for_action(sys_p, user_p)

                    self.colegiado_logger.log_action(
                        round_num=current_round,
                        agent_id=relator.agent_id,
                        agent_name=relator.name,
                        action_type="CREATE_POST",
                        action_args={
                            "content": f"⚖️ [VOTO CONDUTOR DO RELATOR - MÉRITO & DISPOSITIVO]\n\n{content}",
                            "phase": "Voto do Relator",
                            "role": relator.role
                        }
                    )
                    recent_debate_context.append(f"Voto Relator: {content[:400]}")
                    round_actions += 1

            # -------------------------------------------------------------
            # FASE 4: Votos dos Magistrados Vogais & Divergências (Rounds 23 - 35)
            # -------------------------------------------------------------
            elif current_round <= 35:
                if current_round == 24:
                    # 1º Vogal vota (acompanha ou diverge)
                    vogal1 = vogais[0]
                    sys_p = (
                        f"Você é o {vogal1.name}, 1º Desembargador Vogal (Revisor). "
                        f"Sua filosofia hermenêutica é: {vogal1.hermeneutic_profile}. "
                        "Analise o voto do Relator. Você pode:\n"
                        "a) Acompanhar integralmente o Relator;\n"
                        "b) Abrir divergência fundamentada em outro princípio/artigo de lei;\n"
                        "c) Acompanhar com ressalva de entendimento.\n"
                        "Profira seu voto com firmeza e fundamentação técnica."
                    )
                    user_p = f"Voto do Relator:\n{recent_debate_context[-1] if recent_debate_context else ''}"
                    content = await self._call_llm_for_action(sys_p, user_p)

                    self.colegiado_logger.log_action(
                        round_num=current_round,
                        agent_id=vogal1.agent_id,
                        agent_name=vogal1.name,
                        action_type="CREATE_POST",
                        action_args={
                            "content": f"🏛️ [VOTO DO 1º VOGAL / REVISOR]\n\n{content}",
                            "phase": "Votação dos Vogais",
                            "role": vogal1.role
                        }
                    )
                    recent_debate_context.append(f"Voto Vogal 1: {content[:350]}")
                    round_actions += 1

                elif current_round == 28:
                    # 2º Vogal vota
                    vogal2 = vogais[1] if len(vogais) > 1 else vogais[0]
                    sys_p = (
                        f"Você é o {vogal2.name}, 2º Desembargador Vogal. "
                        f"Sua linha de atuação é: {vogal2.hermeneutic_profile}. "
                        "Você tem diante de si o voto do Relator e a manifestação do 1º Vogal. "
                        "Profira seu voto definitivo que comporá o resultado do julgamento."
                    )
                    user_p = f"Votos anteriores:\n{chr(10).join(recent_debate_context[-2:])}"
                    content = await self._call_llm_for_action(sys_p, user_p)

                    self.colegiado_logger.log_action(
                        round_num=current_round,
                        agent_id=vogal2.agent_id,
                        agent_name=vogal2.name,
                        action_type="CREATE_POST",
                        action_args={
                            "content": f"🏛️ [VOTO DO 2º VOGAL]\n\n{content}",
                            "phase": "Votação dos Vogais",
                            "role": vogal2.role
                        }
                    )
                    recent_debate_context.append(f"Voto Vogal 2: {content[:350]}")
                    round_actions += 1

                elif current_round == 32:
                    # Debates orais / Esclarecimento de fato pelos Advogados
                    sys_p = (
                        "Você é o Advogado da parte que teve pontos contrários nos votos. "
                        "Peça a palavra para breve 'ESCLARECIMENTO DE FATO' nos termos do art. 7º do Estatuto da OAB, "
                        "reiterando um ponto probatório crucial para tentar convencer os julgadores antes da proclamação."
                    )
                    user_p = f"Estado da votação:\n{chr(10).join(recent_debate_context[-2:])}"
                    content = await self._call_llm_for_action(sys_p, user_p)

                    self.tribuna_logger.log_action(
                        round_num=current_round,
                        agent_id=adv_autor.agent_id,
                        agent_name=adv_autor.name,
                        action_type="CREATE_COMMENT",
                        action_args={
                            "content": f"📢 [ESCLARECIMENTO DE MATÉRIA DE FATO]\n\n{content}",
                            "phase": "Debates Finais",
                            "role": adv_autor.role,
                            "post_id": 2
                        }
                    )
                    round_actions += 1

            # -------------------------------------------------------------
            # FASE 5: Proclamação do Resultado & Acórdão (Rounds 36 - 40)
            # -------------------------------------------------------------
            else:
                if current_round == 37:
                    # Presidente da Sessão / Relator proclama o resultado
                    sys_p = (
                        "Você é o Presidente do Colegiado proferindo a PROCLAMAÇÃO DO RESULTADO DO JULGAMENTO. "
                        "Anuncie o placar oficial da votação (ex: 'Por unanimidade...', ou 'Por maioria de votos, vencido o 1º Vogal...'). "
                        "Fixe o resultado final do recurso/ação e a súmula do julgamento."
                    )
                    user_p = f"Histórico dos Votos:\n{chr(10).join(recent_debate_context)}"
                    content = await self._call_llm_for_action(sys_p, user_p)

                    self.colegiado_logger.log_action(
                        round_num=current_round,
                        agent_id=relator.agent_id,
                        agent_name="Presidência da Sessão Colegiada",
                        action_type="CREATE_POST",
                        action_args={
                            "content": f"🏆 [PROCLAMAÇÃO DO RESULTADO DO JULGAMENTO]\n\n{content}",
                            "phase": "Proclamação do Julgamento",
                            "role": "Presidente da Sessão"
                        }
                    )
                    round_actions += 1

                elif current_round == self.max_rounds:
                    # Ementa do Acórdão Simulado
                    sys_p = (
                        "Você é o redator do ACÓRDÃO JUDICIAL. Redija a EMENTA OFICIAL em formato forense brasileiro padrão: "
                        "Palavras-chave em caixa alta separadas por ponto, seguidas dos parágrafos numerados sintetizando "
                        "a tese jurídica fixada e o dispositivo do acórdão."
                    )
                    user_p = f"Lide:\n{self.simulation_requirement}\nVotos e Proclamação:\n{chr(10).join(recent_debate_context)}"
                    content = await self._call_llm_for_action(sys_p, user_p)

                    self.colegiado_logger.log_action(
                        round_num=current_round,
                        agent_id=relator.agent_id,
                        agent_name=relator.name,
                        action_type="CREATE_POST",
                        action_args={
                            "content": f"📜 [EMENTA DO ACÓRDÃO SIMULADO]\n\n{content}",
                            "phase": "Publicação do Acórdão",
                            "role": relator.role
                        }
                    )
                    round_actions += 1

            # Log de fim de rodada
            if self.colegiado_logger:
                self.colegiado_logger.log_round_end(current_round, round_actions)
            if self.tribuna_logger:
                self.tribuna_logger.log_round_end(current_round, round_actions)

            total_actions += round_actions
            self.log(f"Rodada {current_round}/{self.max_rounds} concluída ({round_actions} manifestações registradas).")
            await asyncio.sleep(0.5)

        # Encerramento formal de ambos os ambientes para o frontend liberar a geração de relatório
        self.log(f"Sessão encerrada com sucesso! Total de manifestações jurídicas: {total_actions}")
        if self.colegiado_logger:
            self.colegiado_logger.log_simulation_end(total_rounds=self.max_rounds, total_actions=total_actions)
        if self.tribuna_logger:
            self.tribuna_logger.log_simulation_end(total_rounds=self.max_rounds, total_actions=total_actions)
