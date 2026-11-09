"""
本体生成服务
接口1：分析文本内容，生成适合社会模拟的实体和关系类型定义
"""

import json
import logging
import re
from typing import Dict, Any, List, Optional
from ..utils.llm_client import LLMClient
from ..utils.locale import get_language_instruction
from ..utils.file_parser import split_text_into_chunks
from ..utils.ontology import (
    MAX_ONTOLOGY_TYPES,
    normalize_ontology_attributes,
    normalize_ontology_source_targets,
)

logger = logging.getLogger(__name__)


def _to_pascal_case(name: str) -> str:
    """将任意格式的名称转换为 PascalCase（如 'works_for' -> 'WorksFor', 'person' -> 'Person'）"""
    # 按非字母数字字符分割
    parts = re.split(r'[^a-zA-Z0-9]+', name)
    # 再按 camelCase 边界分割（如 'camelCase' -> ['camel', 'Case']）
    words = []
    for part in parts:
        words.extend(re.sub(r'([a-z])([A-Z])', r'\1_\2', part).split('_'))
    # 每个词首字母大写，过滤空串
    result = ''.join(word.capitalize() for word in words if word)
    return result if result else 'Unknown'


def _to_upper_snake_case(name: str) -> str:
    """Convert free-form or camelCase names to SCREAMING_SNAKE_CASE."""

    separated = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', name.strip())
    normalized = re.sub(r'[^a-zA-Z0-9]+', '_', separated).strip('_').upper()
    if not normalized:
        return "UNKNOWN"
    if normalized[0].isdigit():
        normalized = f"REL_{normalized}"
    return normalized


# 本体生成的系统提示词 (Adaptado para Análise e Simulação Jurídica / Colegiada)
ONTOLOGY_SYSTEM_PROMPT = """Você é um especialista em modelagem ontológica e grafos de conhecimento voltados para **SIMULAÇÃO JUDICIAL E JURIMETRIA PREDITIVA (ORÁCULO JURÍDICO)**.
Sua missão é analisar os autos, petição inicial, contestação ou caso fornecido e estruturar uma ontologia perfeita para simular a disputa perante os tribunais brasileiros (STF, STJ, TJs, TRFs, TRTs).

**IMPORTANTE: Você deve retornar EXCLUSIVAMENTE um objeto JSON válido, sem texto conversacional antes ou depois.**

## Contexto do Sistema

Estamos construindo um **Sistema de Simulação Judicial de Alta Precisão**.
Neste sistema:
- Cada entidade é um operador do direito, parte processual, tribunal, preceito legal ou elemento da lide.
- As relações representam vínculos processuais e materiais (ex: ajuizou contra, invocou artigo, acolheu pedido, abriu divergência).

## Tipos de Entidades Essenciais:
- Magistrados (Relatores, Revisores e Vogais com hermenêutica específica)
- Partes (Autor/Agravante e Réu/Agravado)
- Patronos (Advogados constituídos de cada polo)
- Ministério Público (Custos Legis ou parte)
- Dispositivos Legais (Artigos da CF/88, CPC, CC, CP, CLT, CDC)
- Precedentes Vinculantes (Súmulas STF/STJ, Temas de Repercussão Geral)
- Fatos Controvertidos e Pedidos
- Fallback obrigatório: Person e Organization no final da lista de entidades.

## Formato de Saída (JSON estrito)

```json
{
    "entity_types": [
        {
            "name": "NomeTipoEntidade (PascalCase)",
            "description": "Breve descrição em português (até 100 caracteres)",
            "attributes": [
                {
                    "name": "nome_atributo (snake_case)",
                    "type": "text",
                    "description": "Descrição do atributo"
                }
            ],
            "examples": ["Exemplo 1", "Exemplo 2"]
        }
    ],
    "edge_types": [
        {
            "name": "NOME_RELACAO (UPPER_SNAKE_CASE)",
            "description": "Breve descrição (até 100 caracteres)",
            "source_targets": [
                {"source": "TipoOrigem", "target": "TipoDestino"}
            ],
            "attributes": []
        }
    ],
    "analysis_summary": "Síntese dos pontos controvertidos da causa"
}
```

## Regras Obrigatórias:

### 1. Entidades (Exatamente 10 tipos de entidades):
- 8 tipos específicos do domínio jurídico (ex: `Magistrate`, `PlaintiffParty`, `DefendantParty`, `LegalCounsel`, `PublicProsecutor`, `LegalStatute`, `CourtPrecedent`, `ClaimOrThesis`).
- 2 tipos de fallback obrigatórios no final da lista:
  - `Person`: Qualquer pessoa natural envolvida.
  - `Organization`: Qualquer empresa, órgão estatal, tribunal ou autarquia.

### 2. Relações (Entre 6 e 10 tipos):
- Relações forenses como: `SUED_BY`, `REPRESENTS_PARTY`, `RULES_PROCESS`, `CITES_STATUTE`, `APPLIES_PRECEDENT`, `CONTESTS_CLAIM`, `PROVES_FACT`, `OPINES_FOR`, `DIVERGES_FROM`.
- Garantir que `source_targets` utilizem os nomes das entidades declaradas.

### 3. 属性设计

- 每个实体类型1-3个关键属性
- **注意**：属性名不能使用 `name`、`uuid`、`group_id`、`graph_id`、`created_at`、`summary`（这些是系统保留字）
- 推荐使用：`full_name`, `title`, `role`, `position`, `location`, `description` 等

## 实体类型参考

**个人类（具体）**：
- Student: 学生
- Professor: 教授/学者
- Journalist: 记者
- Celebrity: 明星/网红
- Executive: 高管
- Official: 政府官员
- Lawyer: 律师
- Doctor: 医生

**个人类（兜底）**：
- Person: 任何自然人（不属于上述具体类型时使用）

**组织类（具体）**：
- University: 高校
- Company: 公司企业
- GovernmentAgency: 政府机构
- MediaOutlet: 媒体机构
- Hospital: 医院
- School: 中小学
- NGO: 非政府组织

**组织类（兜底）**：
- Organization: 任何组织机构（不属于上述具体类型时使用）

## 关系类型参考

- WORKS_FOR: 工作于
- STUDIES_AT: 就读于
- AFFILIATED_WITH: 隶属于
- REPRESENTS: 代表
- REGULATES: 监管
- REPORTS_ON: 报道
- COMMENTS_ON: 评论
- RESPONDS_TO: 回应
- SUPPORTS: 支持
- OPPOSES: 反对
- COLLABORATES_WITH: 合作
- COMPETES_WITH: 竞争
"""


class OntologyGenerator:
    """
    本体生成器
    分析文本内容，生成实体和关系类型定义
    """
    
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient()
    
    def generate(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        生成本体定义
        
        Args:
            document_texts: 文档文本列表
            simulation_requirement: 模拟需求描述
            additional_context: 额外上下文
            
        Returns:
            本体定义（entity_types, edge_types等）
        """
        # 构建用户消息
        user_message = self._build_user_message(
            document_texts, 
            simulation_requirement,
            additional_context
        )
        
        lang_instruction = get_language_instruction()
        system_prompt = f"{ONTOLOGY_SYSTEM_PROMPT}\n\n{lang_instruction}\nIMPORTANT: Entity type names MUST be in English PascalCase (e.g., 'PersonEntity', 'MediaOrganization'). Relationship type names MUST be in English UPPER_SNAKE_CASE (e.g., 'WORKS_FOR'). Attribute names MUST be in English snake_case. Only description fields and analysis_summary should use the specified language above."
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
        
        # 调用LLM
        result = self.llm_client.chat_json(
            messages=messages,
            temperature=0.3,
            # Structured ontology responses can exceed 4096 completion tokens,
            # especially when a compatible provider counts hidden reasoning in
            # the same budget. Let the provider use its model-specific limit.
            max_tokens=None,
            max_attempts=2,
        )
        
        # 验证和后处理
        result = self._validate_and_process(result)
        
        return result
    
    # 传给 LLM 的文本最大长度（5万字）
    MAX_TEXT_LENGTH_FOR_LLM = 50000
    LONG_TEXT_CHUNK_SIZE = 8000
    LONG_TEXT_CHUNK_OVERLAP = 200
    MAX_LONG_TEXT_CHUNKS = 60
    MIN_LONG_TEXT_EXCERPT = 400
    
    def _build_user_message(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str]
    ) -> str:
        """构建用户消息"""
        
        combined_text = self._build_document_context(document_texts)
        
        message = f"""## 模拟需求

{simulation_requirement}

## 文档内容

{combined_text}
"""
        
        if additional_context:
            message += f"""
## 额外说明

{additional_context}
"""
        
        message += """
请根据以上内容，设计适合社会舆论模拟的实体类型和关系类型。

**必须遵守的规则**：
1. 必须正好输出10个实体类型
2. 最后2个必须是兜底类型：Person（个人兜底）和 Organization（组织兜底）
3. 前8个是根据文本内容设计的具体类型
4. 所有实体类型必须是现实中可以发声的主体，不能是抽象概念
5. 属性名不能使用 name、uuid、group_id、graph_id 等保留字，用 full_name、org_name 等替代
"""
        
        return message

    def _build_document_context(self, document_texts: List[str]) -> str:
        """构建用于本体分析的文档上下文，长文本按全局分块抽样而不是只截取开头。"""

        combined_text = "\n\n---\n\n".join(document_texts)
        original_length = len(combined_text)

        if original_length <= self.MAX_TEXT_LENGTH_FOR_LLM:
            return combined_text

        chunks = self._collect_document_chunks(document_texts)
        if not chunks:
            return ""

        selected_chunks = self._select_representative_chunks(chunks)
        excerpt_budget = self._calculate_excerpt_budget(len(selected_chunks))
        context = self._render_chunked_context(
            selected_chunks=selected_chunks,
            original_length=original_length,
            total_chunks=len(chunks),
            excerpt_limit=excerpt_budget,
        )

        while len(context) > self.MAX_TEXT_LENGTH_FOR_LLM and excerpt_budget > self.MIN_LONG_TEXT_EXCERPT:
            excerpt_budget = max(self.MIN_LONG_TEXT_EXCERPT, int(excerpt_budget * 0.85))
            context = self._render_chunked_context(
                selected_chunks=selected_chunks,
                original_length=original_length,
                total_chunks=len(chunks),
                excerpt_limit=excerpt_budget,
            )

        if len(context) > self.MAX_TEXT_LENGTH_FOR_LLM:
            marker = "\n\n...(分块上下文已压缩到本体分析长度限制内)..."
            context = context[:self.MAX_TEXT_LENGTH_FOR_LLM - len(marker)] + marker

        return context

    def _collect_document_chunks(self, document_texts: List[str]) -> List[Dict[str, Any]]:
        """按文档收集分块，保留文档和分块编号方便提示词定位。"""

        all_chunks: List[Dict[str, Any]] = []
        for doc_index, text in enumerate(document_texts, 1):
            doc_chunks = split_text_into_chunks(
                text,
                chunk_size=self.LONG_TEXT_CHUNK_SIZE,
                overlap=self.LONG_TEXT_CHUNK_OVERLAP,
            )
            total_doc_chunks = len(doc_chunks)
            for chunk_index, chunk in enumerate(doc_chunks, 1):
                all_chunks.append({
                    "document_index": doc_index,
                    "chunk_index": chunk_index,
                    "total_document_chunks": total_doc_chunks,
                    "text": chunk,
                })

        return all_chunks

    def _select_representative_chunks(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """从全部分块中等距抽样，覆盖长文开头、中段和结尾。"""

        if len(chunks) <= self.MAX_LONG_TEXT_CHUNKS:
            return chunks

        if self.MAX_LONG_TEXT_CHUNKS <= 1:
            return [chunks[0]]

        last_index = len(chunks) - 1
        selected_indexes = {
            round(i * last_index / (self.MAX_LONG_TEXT_CHUNKS - 1))
            for i in range(self.MAX_LONG_TEXT_CHUNKS)
        }
        return [chunks[i] for i in sorted(selected_indexes)]

    def _calculate_excerpt_budget(self, selected_count: int) -> int:
        """根据选中的分块数量为每块分配字符预算。"""

        header_budget = 600
        chunk_header_budget = 120 * selected_count
        available = max(
            self.MIN_LONG_TEXT_EXCERPT * selected_count,
            self.MAX_TEXT_LENGTH_FOR_LLM - header_budget - chunk_header_budget,
        )
        return max(self.MIN_LONG_TEXT_EXCERPT, available // max(selected_count, 1))

    def _render_chunked_context(
        self,
        selected_chunks: List[Dict[str, Any]],
        original_length: int,
        total_chunks: int,
        excerpt_limit: int,
    ) -> str:
        """渲染长文本分块上下文。"""

        lines = [
            (
                f"【长文本自动分块摘要】原文共{original_length}字，"
                f"已分为{total_chunks}个文本块用于全局覆盖分析。"
            ),
            (
                f"以下展示其中{len(selected_chunks)}个代表性文本块的摘录，"
                "覆盖开头、中段和结尾；请基于这些跨全文线索设计本体，不要只依赖第一段内容。"
            ),
        ]

        for chunk in selected_chunks:
            excerpt = self._excerpt_text(chunk["text"], excerpt_limit)
            lines.append(
                "\n".join([
                    (
                        f"--- 文档 {chunk['document_index']} / "
                        f"分块 {chunk['chunk_index']}/{chunk['total_document_chunks']} ---"
                    ),
                    excerpt,
                ])
            )

        return "\n\n".join(lines)

    @staticmethod
    def _excerpt_text(text: str, char_limit: int) -> str:
        """长分块保留首尾，避免每个分块内部再次变成只看开头。"""

        text = text.strip()
        if len(text) <= char_limit:
            return text

        marker = "\n...(本分块中间内容省略)...\n"
        if char_limit <= len(marker) + 20:
            return text[:char_limit]

        remaining = char_limit - len(marker)
        head_len = remaining // 2
        tail_len = remaining - head_len
        return f"{text[:head_len].rstrip()}{marker}{text[-tail_len:].lstrip()}"
    
    def _validate_and_process(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """验证和后处理结果"""
        if not isinstance(result, dict):
            raise ValueError("Ontology result must be an object")

        raw_entities = result.get("entity_types")
        raw_edges = result.get("edge_types")
        if not isinstance(raw_entities, list):
            raw_entities = []
        if not isinstance(raw_edges, list):
            raw_edges = []
        if not isinstance(result.get("analysis_summary"), str):
            result["analysis_summary"] = ""

        # Normalize entity entries before touching their fields. LLMs
        # occasionally emit a bare string, null, or another scalar.
        entity_name_map: Dict[str, str] = {}
        processed_entities: List[Dict[str, Any]] = []
        seen_entity_names = set()
        for raw_entity in raw_entities:
            if isinstance(raw_entity, str):
                entity = {"name": raw_entity}
            elif isinstance(raw_entity, dict):
                entity = dict(raw_entity)
            else:
                logger.warning("Ignoring non-object ontology entity entry")
                continue

            original_name = entity.get("name")
            if not isinstance(original_name, str) or not original_name.strip():
                logger.warning("Ignoring ontology entity without a usable name")
                continue
            original_name = original_name.strip()
            normalized_name = _to_pascal_case(original_name)
            if normalized_name == "Unknown":
                continue
            if normalized_name in seen_entity_names:
                logger.warning(f"Duplicate entity type '{normalized_name}' removed during validation")
                entity_name_map[original_name] = normalized_name
                entity_name_map[original_name.lower()] = normalized_name
                continue

            if normalized_name != original_name:
                logger.warning(
                    f"Entity type name '{original_name}' auto-converted to '{normalized_name}'"
                )
            entity["name"] = normalized_name
            entity["attributes"] = normalize_ontology_attributes(
                entity.get("attributes", [])
            )
            if not isinstance(entity.get("examples"), list):
                entity["examples"] = []
            description = entity.get("description")
            if not isinstance(description, str) or not description:
                description = f"A {normalized_name} entity."
            entity["description"] = (
                description[:97] + "..." if len(description) > 100 else description
            )

            seen_entity_names.add(normalized_name)
            processed_entities.append(entity)
            entity_name_map[original_name] = normalized_name
            entity_name_map[original_name.lower()] = normalized_name
            entity_name_map[normalized_name] = normalized_name
            entity_name_map[normalized_name.lower()] = normalized_name

        result["entity_types"] = processed_entities

        # 兜底类型定义
        person_fallback = {
            "name": "Person",
            "description": "Any individual person not fitting other specific person types.",
            "attributes": [
                {"name": "full_name", "type": "text", "description": "Full name of the person"},
                {"name": "role", "type": "text", "description": "Role or occupation"}
            ],
            "examples": ["ordinary citizen", "anonymous netizen"]
        }
        
        organization_fallback = {
            "name": "Organization",
            "description": "Any organization not fitting other specific organization types.",
            "attributes": [
                {"name": "org_name", "type": "text", "description": "Name of the organization"},
                {"name": "org_type", "type": "text", "description": "Type of organization"}
            ],
            "examples": ["small business", "community group"]
        }
        
        # 检查是否已有兜底类型
        entity_names = {e["name"] for e in result["entity_types"]}
        has_person = "Person" in entity_names
        has_organization = "Organization" in entity_names
        
        # 需要添加的兜底类型
        fallbacks_to_add = []
        if not has_person:
            fallbacks_to_add.append(person_fallback)
        if not has_organization:
            fallbacks_to_add.append(organization_fallback)
        
        if fallbacks_to_add:
            current_count = len(result["entity_types"])
            needed_slots = len(fallbacks_to_add)
            
            # 如果添加后会超过 10 个，需要移除一些现有类型
            if current_count + needed_slots > MAX_ONTOLOGY_TYPES:
                # 计算需要移除多少个
                to_remove = current_count + needed_slots - MAX_ONTOLOGY_TYPES
                # 从末尾移除（保留前面更重要的具体类型）
                result["entity_types"] = result["entity_types"][:-to_remove]
            
            # 添加兜底类型
            result["entity_types"].extend(fallbacks_to_add)
        
        # 最终确保不超过限制（防御性编程）
        result["entity_types"] = result["entity_types"][:MAX_ONTOLOGY_TYPES]

        # Resolve edge endpoints only after entity fallback/capping, so an edge
        # cannot refer to a type that was removed to satisfy Zep's limits.
        valid_entity_names = {entity["name"] for entity in result["entity_types"]}
        for name in valid_entity_names:
            entity_name_map[name] = name
            entity_name_map[name.lower()] = name

        def resolve_entity_name(value: str) -> Optional[str]:
            stripped = value.strip()
            if stripped == "Entity":
                return stripped
            mapped = entity_name_map.get(stripped) or entity_name_map.get(stripped.lower())
            if mapped in valid_entity_names:
                return mapped
            pascal_name = _to_pascal_case(stripped)
            return pascal_name if pascal_name in valid_entity_names else None

        processed_edges: List[Dict[str, Any]] = []
        seen_edge_names = set()
        for raw_edge in raw_edges:
            if isinstance(raw_edge, str):
                # A bare edge name has no endpoints and cannot be installed in
                # Zep safely. Ignore it instead of inventing a relationship.
                logger.warning(f"Ignoring ontology edge without source_targets: {raw_edge}")
                continue
            elif isinstance(raw_edge, dict):
                edge = dict(raw_edge)
            else:
                logger.warning("Ignoring non-object ontology edge entry")
                continue

            original_name = edge.get("name")
            if not isinstance(original_name, str) or not original_name.strip():
                logger.warning("Ignoring ontology edge without a usable name")
                continue
            normalized_name = _to_upper_snake_case(original_name)
            if normalized_name == "UNKNOWN" or normalized_name in seen_edge_names:
                if normalized_name in seen_edge_names:
                    logger.warning(f"Duplicate edge type '{normalized_name}' removed during validation")
                continue
            if normalized_name != original_name:
                logger.warning(
                    f"Edge type name '{original_name}' auto-converted to '{normalized_name}'"
                )
            edge["name"] = normalized_name

            normalized_targets = []
            for source_target in normalize_ontology_source_targets(
                edge.get("source_targets", []),
                limit=None,
            ):
                source = resolve_entity_name(source_target["source"])
                target = resolve_entity_name(source_target["target"])
                if source and target:
                    normalized_targets.append({"source": source, "target": target})
            edge["source_targets"] = normalize_ontology_source_targets(
                normalized_targets
            )
            edge["attributes"] = normalize_ontology_attributes(
                edge.get("attributes", [])
            )
            description = edge.get("description")
            if not isinstance(description, str) or not description:
                description = f"A {normalized_name} relationship."
            edge["description"] = (
                description[:97] + "..." if len(description) > 100 else description
            )

            seen_edge_names.add(normalized_name)
            processed_edges.append(edge)
            if len(processed_edges) == MAX_ONTOLOGY_TYPES:
                break

        result["edge_types"] = processed_edges
        
        return result
    
    def generate_python_code(self, ontology: Dict[str, Any]) -> str:
        """
        将本体定义转换为Python代码（类似ontology.py）
        
        Args:
            ontology: 本体定义
            
        Returns:
            Python代码字符串
        """
        code_lines = [
            '"""',
            '自定义实体类型定义',
            '由MiroFish自动生成，用于社会舆论模拟',
            '"""',
            '',
            'from pydantic import Field',
            'from zep_cloud.external_clients.ontology import EntityModel, EntityText, EdgeModel',
            '',
            '',
            '# ============== 实体类型定义 ==============',
            '',
        ]
        
        # 生成实体类型
        for entity in ontology.get("entity_types", []):
            name = entity["name"]
            desc = entity.get("description", f"A {name} entity.")
            
            code_lines.append(f'class {name}(EntityModel):')
            code_lines.append(f'    """{desc}"""')
            
            attrs = entity.get("attributes", [])
            if attrs:
                for attr in attrs:
                    attr_name = attr["name"]
                    attr_desc = attr.get("description", attr_name)
                    code_lines.append(f'    {attr_name}: EntityText = Field(')
                    code_lines.append(f'        description="{attr_desc}",')
                    code_lines.append(f'        default=None')
                    code_lines.append(f'    )')
            else:
                code_lines.append('    pass')
            
            code_lines.append('')
            code_lines.append('')
        
        code_lines.append('# ============== 关系类型定义 ==============')
        code_lines.append('')
        
        # 生成关系类型
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            # 转换为PascalCase类名
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            desc = edge.get("description", f"A {name} relationship.")
            
            code_lines.append(f'class {class_name}(EdgeModel):')
            code_lines.append(f'    """{desc}"""')
            
            attrs = edge.get("attributes", [])
            if attrs:
                for attr in attrs:
                    attr_name = attr["name"]
                    attr_desc = attr.get("description", attr_name)
                    code_lines.append(f'    {attr_name}: EntityText = Field(')
                    code_lines.append(f'        description="{attr_desc}",')
                    code_lines.append(f'        default=None')
                    code_lines.append(f'    )')
            else:
                code_lines.append('    pass')
            
            code_lines.append('')
            code_lines.append('')
        
        # 生成类型字典
        code_lines.append('# ============== 类型配置 ==============')
        code_lines.append('')
        code_lines.append('ENTITY_TYPES = {')
        for entity in ontology.get("entity_types", []):
            name = entity["name"]
            code_lines.append(f'    "{name}": {name},')
        code_lines.append('}')
        code_lines.append('')
        code_lines.append('EDGE_TYPES = {')
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            code_lines.append(f'    "{name}": {class_name},')
        code_lines.append('}')
        code_lines.append('')
        
        # 生成边的source_targets映射
        code_lines.append('EDGE_SOURCE_TARGETS = {')
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            source_targets = edge.get("source_targets", [])
            if source_targets:
                st_list = ', '.join([
                    f'{{"source": "{st.get("source", "Entity")}", "target": "{st.get("target", "Entity")}"}}'
                    for st in source_targets
                ])
                code_lines.append(f'    "{name}": [{st_list}],')
        code_lines.append('}')
        
        return '\n'.join(code_lines)
