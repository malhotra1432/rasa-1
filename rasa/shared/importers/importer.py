import asyncio
from functools import reduce
from typing import Text, Optional, List, Dict, Set, Any
import logging

import rasa.shared.constants
import rasa.shared.utils.common
import rasa.shared.core.constants
import rasa.shared.utils.io
from rasa.shared.core.domain import Domain
from rasa.shared.core.events import ActionExecuted, UserUttered, Event
from rasa.shared.nlu.interpreter import NaturalLanguageInterpreter, RegexInterpreter
from rasa.shared.core.training_data.structures import StoryGraph
from rasa.shared.nlu.training_data.message import Message
from rasa.shared.nlu.training_data.training_data import TrainingData
from rasa.shared.nlu.constants import INTENT_NAME, TEXT
from rasa.shared.importers.autoconfig import TrainingType
from rasa.shared.core.domain import IS_RETRIEVAL_INTENT_KEY

logger = logging.getLogger(__name__)


class TrainingDataImporter:
    """Common interface for different mechanisms to load training data."""

    async def get_domain(self) -> Domain:
        """Retrieves the domain of the bot.

        Returns:
            Loaded `Domain`.
        """
        raise NotImplementedError()

    async def get_stories(
        self,
        template_variables: Optional[Dict] = None,
        use_e2e: bool = False,
        exclusion_percentage: Optional[int] = None,
    ) -> StoryGraph:
        """Retrieves the stories that should be used for training.

        Args:
            template_variables: Values of templates that should be replaced while
                                reading the story files.
            use_e2e: Specifies whether to parse end to end learning annotations.
            exclusion_percentage: Amount of training data that should be excluded.

        Returns:
            `StoryGraph` containing all loaded stories.
        """

        raise NotImplementedError()

    async def get_config(self) -> Dict:
        """Retrieves the configuration that should be used for the training.

        Returns:
            The configuration as dictionary.
        """

        raise NotImplementedError()

    async def get_nlu_data(self, language: Optional[Text] = "en") -> TrainingData:
        """Retrieves the NLU training data that should be used for training.

        Args:
            language: Can be used to only load training data for a certain language.

        Returns:
            Loaded NLU `TrainingData`.
        """

        raise NotImplementedError()

    @staticmethod
    def load_from_config(
        config_path: Text,
        domain_path: Optional[Text] = None,
        training_data_paths: Optional[List[Text]] = None,
        training_type: Optional[TrainingType] = TrainingType.BOTH,
    ) -> "TrainingDataImporter":
        """Loads a `TrainingDataImporter` instance from a configuration file."""

        config = rasa.shared.utils.io.read_config_file(config_path)
        return TrainingDataImporter.load_from_dict(
            config, config_path, domain_path, training_data_paths, training_type
        )

    @staticmethod
    def load_core_importer_from_config(
        config_path: Text,
        domain_path: Optional[Text] = None,
        training_data_paths: Optional[List[Text]] = None,
    ) -> "TrainingDataImporter":
        """Loads core `TrainingDataImporter` instance.

        Instance loaded from configuration file will only read Core training data.
        """

        importer = TrainingDataImporter.load_from_config(
            config_path, domain_path, training_data_paths, TrainingType.CORE
        )

        return CoreDataImporter(importer)

    @staticmethod
    def load_nlu_importer_from_config(
        config_path: Text,
        domain_path: Optional[Text] = None,
        training_data_paths: Optional[List[Text]] = None,
    ) -> "TrainingDataImporter":
        """Loads nlu `TrainingDataImporter` instance.

        Instance loaded from configuration file will only read NLU training data.
        """

        importer = TrainingDataImporter.load_from_config(
            config_path, domain_path, training_data_paths, TrainingType.NLU
        )

        if isinstance(importer, E2EImporter):
            # When we only train NLU then there is no need to enrich the data with
            # E2E data from Core training data.
            importer = importer.importer

        return NluDataImporter(importer)

    @staticmethod
    def load_from_dict(
        config: Optional[Dict],
        config_path: Text,
        domain_path: Optional[Text] = None,
        training_data_paths: Optional[List[Text]] = None,
        training_type: Optional[TrainingType] = TrainingType.BOTH,
    ) -> "TrainingDataImporter":
        """Loads a `TrainingDataImporter` instance from a dictionary."""

        from rasa.shared.importers.rasa import RasaFileImporter

        config = config or {}
        importers = config.get("importers", [])
        importers = [
            TrainingDataImporter._importer_from_dict(
                importer, config_path, domain_path, training_data_paths, training_type
            )
            for importer in importers
        ]
        importers = [importer for importer in importers if importer]

        if not importers:
            importers = [
                RasaFileImporter(
                    config_path, domain_path, training_data_paths, training_type
                )
            ]

        return E2EImporter(RetrievalModelsDataImporter(CombinedDataImporter(importers)))

    @staticmethod
    def _importer_from_dict(
        importer_config: Dict,
        config_path: Text,
        domain_path: Optional[Text] = None,
        training_data_paths: Optional[List[Text]] = None,
        training_type: Optional[TrainingType] = TrainingType.BOTH,
    ) -> Optional["TrainingDataImporter"]:
        from rasa.shared.importers.multi_project import MultiProjectImporter
        from rasa.shared.importers.rasa import RasaFileImporter

        module_path = importer_config.pop("name", None)
        if module_path == RasaFileImporter.__name__:
            importer_class = RasaFileImporter
        elif module_path == MultiProjectImporter.__name__:
            importer_class = MultiProjectImporter
        else:
            try:
                importer_class = rasa.shared.utils.common.class_from_module_path(
                    module_path
                )
            except (AttributeError, ImportError):
                logging.warning(f"Importer '{module_path}' not found.")
                return None

        importer_config = dict(training_type=training_type, **importer_config)

        constructor_arguments = rasa.shared.utils.common.minimal_kwargs(
            importer_config, importer_class
        )

        return importer_class(
            config_path, domain_path, training_data_paths, **constructor_arguments
        )


class NluDataImporter(TrainingDataImporter):
    """Importer that skips any Core-related file reading."""

    def __init__(self, actual_importer: TrainingDataImporter):
        self._importer = actual_importer

    async def get_domain(self) -> Domain:
        return Domain.empty()

    async def get_stories(
        self,
        template_variables: Optional[Dict] = None,
        use_e2e: bool = False,
        exclusion_percentage: Optional[int] = None,
    ) -> StoryGraph:
        return StoryGraph([])

    async def get_config(self) -> Dict:
        return await self._importer.get_config()

    async def get_nlu_data(self, language: Optional[Text] = "en") -> TrainingData:
        return await self._importer.get_nlu_data(language)


class CoreDataImporter(TrainingDataImporter):
    """Importer that skips any NLU related file reading."""

    def __init__(self, actual_importer: TrainingDataImporter):
        self._importer = actual_importer

    async def get_domain(self) -> Domain:
        return await self._importer.get_domain()

    async def get_stories(
        self,
        template_variables: Optional[Dict] = None,
        use_e2e: bool = False,
        exclusion_percentage: Optional[int] = None,
    ) -> StoryGraph:
        return await self._importer.get_stories(
            template_variables, use_e2e, exclusion_percentage
        )

    async def get_config(self) -> Dict:
        return await self._importer.get_config()

    async def get_nlu_data(self, language: Optional[Text] = "en") -> TrainingData:
        return TrainingData()


class CombinedDataImporter(TrainingDataImporter):
    """A `TrainingDataImporter` that combines multiple importers.
    Uses multiple `TrainingDataImporter` instances
    to load the data as if they were a single instance.
    """

    def __init__(self, importers: List[TrainingDataImporter]):
        self._importers = importers

    async def get_config(self) -> Dict:
        configs = [importer.get_config() for importer in self._importers]
        configs = await asyncio.gather(*configs)

        return reduce(lambda merged, other: {**merged, **(other or {})}, configs, {})

    async def get_domain(self) -> Domain:
        domains = [importer.get_domain() for importer in self._importers]
        domains = await asyncio.gather(*domains)

        return reduce(
            lambda merged, other: merged.merge(other), domains, Domain.empty()
        )

    async def get_stories(
        self,
        template_variables: Optional[Dict] = None,
        use_e2e: bool = False,
        exclusion_percentage: Optional[int] = None,
    ) -> StoryGraph:
        stories = [
            importer.get_stories(template_variables, use_e2e, exclusion_percentage)
            for importer in self._importers
        ]
        stories = await asyncio.gather(*stories)

        return reduce(
            lambda merged, other: merged.merge(other), stories, StoryGraph([])
        )

    async def get_nlu_data(self, language: Optional[Text] = "en") -> TrainingData:
        nlu_data = [importer.get_nlu_data(language) for importer in self._importers]
        nlu_data = await asyncio.gather(*nlu_data)

        return reduce(
            lambda merged, other: merged.merge(other), nlu_data, TrainingData()
        )


class RetrievalModelsDataImporter(TrainingDataImporter):
    """A `TrainingDataImporter` that sets up the data for training retrieval models.

    Synchronizes response templates between Domain and NLU
    and adds retrieval intent properties from the NLU training data
    back to the Domain.
    """

    def __init__(self, importer: TrainingDataImporter):
        self._importer = importer

    async def get_config(self) -> Dict:
        return await self._importer.get_config()

    async def get_domain(self) -> Domain:
        """Merge existing domain with properties of retrieval intents in NLU data."""

        existing_domain = await self._importer.get_domain()
        existing_nlu_data = await self._importer.get_nlu_data()

        # Check if NLU data has any retrieval intents, if yes
        # add corresponding retrieval actions with `utter_` prefix automatically
        # to an empty domain, update the properties of existing retrieval intents
        # and merge response templates
        if existing_nlu_data.retrieval_intents:

            domain_with_retrieval_intents = self._get_domain_with_retrieval_intents(
                existing_nlu_data.retrieval_intents,
                existing_nlu_data.responses,
                existing_domain,
            )

            existing_domain = existing_domain.merge(domain_with_retrieval_intents)

        return existing_domain

    @staticmethod
    def _construct_retrieval_action_names(retrieval_intents: Set[Text]) -> List[Text]:
        """List names of all retrieval actions corresponding to passed retrieval intents.

        Args:
            retrieval_intents: List of retrieval intents defined in the NLU training data.

        Returns: Names of corresponding retrieval actions
        """

        return [
            f"{rasa.shared.constants.UTTER_PREFIX}{intent}"
            for intent in retrieval_intents
        ]

    @staticmethod
    def _get_domain_with_retrieval_intents(
        retrieval_intents: Set[Text],
        response_templates: Dict[Text, List[Dict[Text, Any]]],
        existing_domain: Domain,
    ) -> Domain:
        """Construct a domain consisting of retrieval intents listed in the NLU training data.

        Args:
            retrieval_intents: Set of retrieval intents defined in NLU training data.
            existing_domain: Domain which is already loaded from the domain file.

        Returns: Domain with retrieval actions added to action names and properties
        for retrieval intents updated.
        """

        # Get all the properties already defined
        # for each retrieval intent in other domains
        # and add the retrieval intent property to them
        retrieval_intent_properties = []
        for intent in retrieval_intents:
            intent_properties = (
                existing_domain.intent_properties[intent]
                if intent in existing_domain.intent_properties
                else {}
            )
            intent_properties[IS_RETRIEVAL_INTENT_KEY] = True
            retrieval_intent_properties.append({intent: intent_properties})

        return Domain(
            retrieval_intent_properties,
            [],
            [],
            response_templates,
            RetrievalModelsDataImporter._construct_retrieval_action_names(
                retrieval_intents
            ),
            [],
        )

    async def get_stories(
        self,
        template_variables: Optional[Dict] = None,
        use_e2e: bool = False,
        exclusion_percentage: Optional[int] = None,
    ) -> StoryGraph:

        return await self._importer.get_stories(
            template_variables, use_e2e, exclusion_percentage
        )

    async def get_nlu_data(self, language: Optional[Text] = "en") -> TrainingData:
        """Update NLU data with response templates defined in the domain"""

        existing_nlu_data = await self._importer.get_nlu_data(language)
        existing_domain = await self._importer.get_domain()

        return existing_nlu_data.merge(
            self._get_nlu_data_with_responses(existing_domain.templates)
        )

    @staticmethod
    def _get_nlu_data_with_responses(
        response_templates: Dict[Text, List[Dict[Text, Any]]]
    ) -> TrainingData:
        """Construct training data object with only the response templates supplied.

        Args:
            response_templates: Response templates the NLU data should
            be initialized with.

        Returns: TrainingData object with response templates.

        """

        return TrainingData(responses=response_templates)


class E2EImporter(TrainingDataImporter):
    """Importer which
    - enhances the NLU training data with actions / user messages from the stories.
    - adds potential end-to-end bot messages from stories as actions to the domain
    """

    def __init__(self, importer: TrainingDataImporter) -> None:

        self.importer = importer
        self._cached_stories: Optional[StoryGraph] = None

    async def get_domain(self) -> Domain:
        original, e2e_domain = await asyncio.gather(
            self.importer.get_domain(), self._get_domain_with_e2e_actions()
        )
        return original.merge(e2e_domain)

    async def _get_domain_with_e2e_actions(self) -> Domain:
        from rasa.shared.core.events import ActionExecuted

        stories = await self.get_stories()

        additional_e2e_action_names = set()
        for story_step in stories.story_steps:
            additional_e2e_action_names.update(
                {
                    event.action_text
                    for event in story_step.events
                    if isinstance(event, ActionExecuted) and event.action_text
                }
            )

        additional_e2e_action_names = list(additional_e2e_action_names)

        return Domain(
            [], [], [], {}, action_names=additional_e2e_action_names, forms=[]
        )

    async def get_stories(
        self,
        interpreter: "NaturalLanguageInterpreter" = RegexInterpreter(),
        template_variables: Optional[Dict] = None,
        use_e2e: bool = False,
        exclusion_percentage: Optional[int] = None,
    ) -> StoryGraph:
        if not self._cached_stories:
            # Simple cache to avoid loading all of this multiple times
            self._cached_stories = await self.importer.get_stories(
                template_variables, use_e2e, exclusion_percentage
            )
        return self._cached_stories

    async def get_config(self) -> Dict:
        return await self.importer.get_config()

    async def get_nlu_data(self, language: Optional[Text] = "en") -> TrainingData:
        training_datasets = [_additional_training_data_from_default_actions()]

        training_datasets += await asyncio.gather(
            self.importer.get_nlu_data(language),
            self._additional_training_data_from_stories(),
        )

        return reduce(
            lambda merged, other: merged.merge(other), training_datasets, TrainingData()
        )

    async def _additional_training_data_from_stories(self) -> TrainingData:
        stories = await self.get_stories()

        additional_messages_from_stories = []
        for story_step in stories.story_steps:
            for event in story_step.events:
                message = _message_from_conversation_event(event)
                if message:
                    additional_messages_from_stories.append(message)

        logger.debug(
            f"Added {len(additional_messages_from_stories)} training data examples "
            f"from the story training data."
        )
        return TrainingData(additional_messages_from_stories)


def _message_from_conversation_event(event: Event) -> Optional[Message]:
    if isinstance(event, UserUttered):
        return _messages_from_user_utterance(event)
    elif isinstance(event, ActionExecuted):
        return _messages_from_action(event)

    return None


def _messages_from_user_utterance(event: UserUttered) -> Message:
    return Message(data={TEXT: event.text, INTENT_NAME: event.intent_name})


def _messages_from_action(event: ActionExecuted) -> Message:
    return Message.build_from_action(
        action_name=event.action_name, action_text=event.action_text or ""
    )


def _additional_training_data_from_default_actions() -> TrainingData:
    additional_messages_from_default_actions = [
        Message.build_from_action(action_name=action_name)
        for action_name in rasa.shared.core.constants.DEFAULT_ACTION_NAMES
    ]

    return TrainingData(additional_messages_from_default_actions)
